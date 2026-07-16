"""Solana session-intent payment core (draft-solana-session-00).

Off-chain metered payments backed by on-chain channel escrow. The client opens a
channel (on-chain), then signs cumulative-amount VOUCHERS off-chain; the server
meters actual usage against the highest accepted voucher and settles once at
close. This module is the server-side voucher verification + metering state; the
FastAPI gate lives in middleware.py and the channel program in solana/.

Voucher signed-bytes layout (48 bytes, must match the channel program):
    channel_pubkey(32) || cumulative_amount(u64 LE) || expires_at(i64 LE)
"""

from __future__ import annotations

import base64
import struct
import time
from dataclasses import dataclass, field

from nacl.signing import VerifyKey


def voucher_message(channel: bytes, cumulative: int, expires_at: int) -> bytes:
    if len(channel) != 32:
        raise ValueError("channel must be 32 bytes")
    return channel + struct.pack("<Q", cumulative) + struct.pack("<q", expires_at)


@dataclass
class Voucher:
    channel_b58: str          # channel PDA (base58)
    channel_bytes: bytes      # 32-byte channel pubkey
    cumulative_amount: int    # micro-USDC, cumulative (monotonic)
    expires_at: int           # unix seconds
    signer_pubkey: bytes      # 32-byte ed25519 authorized signer
    signature: bytes          # 64-byte ed25519 sig over voucher_message

    def verify(self) -> bool:
        try:
            VerifyKey(self.signer_pubkey).verify(
                voucher_message(self.channel_bytes, self.cumulative_amount, self.expires_at),
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
    authorized_signer: bytes          # who may sign vouchers (from on-chain)
    deposit: int                      # escrowed micro-USDC (from on-chain)
    accepted_cumulative: int = 0      # highest verified voucher amount
    spent: int = 0                    # metered so far
    status: str = "open"              # open | closing | finalized

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
        if amount > self.available:
            raise InsufficientFunds(need=amount, available=self.available)
        self.spent += amount


class InsufficientFunds(Exception):
    def __init__(self, need: int, available: int):
        self.need = need
        self.available = available
        super().__init__(f"need {need} micro-USDC, only {available} authorized")


@dataclass
class ChannelStore:
    """In-memory channel registry (P5: back with on-chain reads at open/close)."""
    channels: dict[str, Channel] = field(default_factory=dict)

    def open(self, channel_b58: str, channel_bytes: bytes, authorized_signer: bytes,
             deposit: int) -> Channel:
        ch = Channel(channel_b58=channel_b58, authorized_signer=authorized_signer,
                     deposit=deposit)
        self.channels[channel_b58] = ch
        return ch

    def get(self, channel_b58: str) -> Channel | None:
        return self.channels.get(channel_b58)


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
