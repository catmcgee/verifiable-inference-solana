"""Vinfer's experimental Solana payment channel core.

Off-chain metered payments backed by on-chain channel escrow. The client opens a
channel (on-chain), then signs cumulative-amount VOUCHERS off-chain; the server
meters actual usage against the highest accepted voucher and settles once at
close. This module is the server-side voucher verification + metering state; the
FastAPI gate lives in middleware.py and the channel program in solana/.

This predates and does not implement draft-solana-session-00. In particular,
the draft has a different PDA/state layout, canonical SignedVoucher encoding,
tombstones, idempotency rules, and settlement/finalization semantics. See
DESIGN.md. The public scheme name is deliberately ``vinfer-session-v1``.

Voucher signed-bytes layout (48 bytes, must match the channel program):
    channel_pubkey(32) || cumulative_amount(u64 LE) || expires_at(i64 LE)
"""

from __future__ import annotations

import os
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from nacl.signing import VerifyKey


def voucher_message(channel: bytes, cumulative: int, expires_at: int) -> bytes:
    if len(channel) != 32:
        raise ValueError("channel must be 32 bytes")
    return channel + struct.pack("<Q", cumulative) + struct.pack("<q", expires_at)


@dataclass
class Voucher:
    channel_b58: str  # channel PDA (base58)
    channel_bytes: bytes  # 32-byte channel pubkey
    cumulative_amount: int  # micro-USDC, cumulative (monotonic)
    expires_at: int  # unix seconds
    signer_pubkey: bytes  # 32-byte ed25519 authorized signer
    signature: bytes  # 64-byte ed25519 sig over voucher_message

    def verify(self) -> bool:
        try:
            VerifyKey(self.signer_pubkey).verify(
                voucher_message(
                    self.channel_bytes, self.cumulative_amount, self.expires_at
                ),
                self.signature,
            )
            return self.expires_at == 0 or self.expires_at >= int(time.time())
        except Exception:
            return False


@dataclass
class Channel:
    """Server-side view of one payment channel. `deposit`/`authorized_signer`
    come from the on-chain open; `spent` is the server's metered debit."""

    channel_b58: str
    authorized_signer: bytes  # who may sign vouchers (from on-chain)
    deposit: int  # escrowed micro-USDC (from on-chain)
    opened_slot: int = 0
    payer: str = ""
    payee: str = ""
    mint: str = ""
    vault: str = ""
    accepted_cumulative: int = 0  # highest verified voucher amount
    spent: int = 0  # metered so far
    status: str = "open"  # open | closing | finalized

    @property
    def available(self) -> int:
        return self.accepted_cumulative - self.spent

    def accept_voucher(self, v: Voucher) -> None:
        if v.channel_b58 != self.channel_b58:
            raise ValueError("voucher channel mismatch")
        if v.signer_pubkey != self.authorized_signer:
            raise ValueError("voucher signer is not the channel's authorized signer")
        if not v.verify():
            raise ValueError("voucher signature invalid or expired")
        if v.cumulative_amount > self.deposit:
            raise ValueError("voucher exceeds channel deposit")
        if v.cumulative_amount < self.accepted_cumulative:
            raise ValueError("voucher cumulative went backwards (replay/stale)")
        self.accepted_cumulative = v.cumulative_amount

    def debit(self, amount: int) -> None:
        """Persist a debit BEFORE serving (spec step 3). Raises if insufficient."""
        if self.status != "open":
            raise ValueError("channel is not open")
        if amount < 0:
            raise ValueError("debit cannot be negative")
        if amount > self.available:
            raise InsufficientFunds(need=amount, available=self.available)
        self.spent += amount


class InsufficientFunds(Exception):
    def __init__(self, need: int, available: int):
        self.need = need
        self.available = available
        super().__init__(f"need {need} micro-USDC, only {available} authorized")


class ChannelStore:
    """Durable channel meter. Credentials are never stored, only counters."""

    def __init__(self, path: str | Path | None = None):
        default = Path.home() / ".local" / "state" / "vinfer" / "channels.sqlite3"
        self.path = Path(path or os.environ.get("VINFER_CHANNEL_DB", default))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                opened_slot INTEGER NOT NULL,
                authorized_signer BLOB NOT NULL,
                payer TEXT NOT NULL,
                payee TEXT NOT NULL,
                mint TEXT NOT NULL,
                vault TEXT NOT NULL,
                deposit INTEGER NOT NULL,
                accepted_cumulative INTEGER NOT NULL,
                spent INTEGER NOT NULL,
                status TEXT NOT NULL
            )
        """)
        self._db.commit()

    @staticmethod
    def _channel(row: tuple) -> Channel:
        return Channel(
            channel_b58=row[0],
            opened_slot=row[1],
            authorized_signer=row[2],
            payer=row[3],
            payee=row[4],
            mint=row[5],
            vault=row[6],
            deposit=row[7],
            accepted_cumulative=row[8],
            spent=row[9],
            status=row[10],
        )

    def _get(self, channel_b58: str) -> Channel | None:
        row = self._db.execute(
            "SELECT channel_id, opened_slot, authorized_signer, payer, payee, mint, "
            "vault, deposit, accepted_cumulative, spent, status FROM channels "
            "WHERE channel_id = ?",
            (channel_b58,),
        ).fetchone()
        return self._channel(row) if row else None

    def sync_onchain(self, account) -> Channel:
        """Hydrate immutable fields/deposit/status from a verified RPC account."""
        with self._lock, self._db:
            old = self._get(account.address)
            if old is None or old.opened_slot != account.opened_slot:
                accepted = account.authorized_cumulative
                spent = account.settled
            else:
                accepted = max(old.accepted_cumulative, account.authorized_cumulative)
                spent = max(old.spent, account.settled)
            if not (0 <= spent <= accepted <= account.deposit):
                raise ValueError("on-chain and local channel counters are inconsistent")
            self._db.execute(
                "INSERT OR REPLACE INTO channels VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    account.address,
                    account.opened_slot,
                    account.authorized_signer,
                    account.payer,
                    account.payee,
                    account.mint,
                    account.vault,
                    account.deposit,
                    accepted,
                    spent,
                    account.status,
                ),
            )
            return self._get(account.address)  # type: ignore[return-value]

    def get(self, channel_b58: str) -> Channel | None:
        with self._lock:
            return self._get(channel_b58)

    def authorize_and_debit(self, voucher: Voucher, amount: int) -> Channel:
        with self._lock, self._db:
            channel = self._get(voucher.channel_b58)
            if channel is None:
                raise ValueError("unknown channel; send action=open first")
            channel.accept_voucher(voucher)
            channel.debit(amount)
            self._db.execute(
                "UPDATE channels SET accepted_cumulative = ?, spent = ? WHERE channel_id = ?",
                (channel.accepted_cumulative, channel.spent, channel.channel_b58),
            )
            return channel

    def reconcile(self, channel_b58: str, quote: int, actual: int) -> Channel:
        with self._lock, self._db:
            channel = self._get(channel_b58)
            if channel is None:
                raise ValueError("unknown channel")
            refund = max(0, quote - actual)
            channel.spent -= refund
            self._db.execute(
                "UPDATE channels SET spent = ? WHERE channel_id = ?",
                (channel.spent, channel.channel_b58),
            )
            return channel


def parse_voucher(d: dict) -> Voucher:
    """Parse a voucher from the credentials JSON. channelId + signer are base58
    (Solana convention); signature is base64 or base58."""
    return Voucher(
        channel_b58=d["channelId"],
        channel_bytes=_b58decode(d["channelId"]),
        cumulative_amount=int(d["cumulativeAmount"]),
        expires_at=int(d.get("expiresAt", 0)),
        signer_pubkey=_decode_key(d["signer"]),
        signature=_decode_key(d["signature"]),
    )


def _b58decode(s: str) -> bytes:
    from solders.pubkey import Pubkey

    return bytes(Pubkey.from_string(s))


def _decode_key(s: str) -> bytes:
    """Accept base64 (has +,/,= or non-b58 chars) or base58."""
    import base64 as _b64

    try:
        raw = _b64.b64decode(s, validate=True)
        if len(raw) in (32, 64):
            return raw
    except Exception:
        pass
    return _b58decode(s)
