"""Read and validate vinfer-session-v1 channel accounts from Solana."""

from __future__ import annotations

import base64
import hashlib
import os
import struct
from dataclasses import dataclass

import httpx
from solders.pubkey import Pubkey


PROGRAM_ID = Pubkey.from_string(
    os.environ.get(
        "VINFER_CHANNEL_PROGRAM",
        "Dp5LxL9XHZUVXK129rxwBafqHMg1Y29Zda2svx8vXEkx",
    )
)
RPC = os.environ.get("VINFER_SOLANA_RPC", "https://api.devnet.solana.com")
DISCRIMINATOR = hashlib.sha256(b"account:ChannelAccount").digest()[:8]


@dataclass(frozen=True)
class OnchainChannel:
    address: str
    payer: str
    payee: str
    mint: str
    vault: str
    authorized_signer: bytes
    channel_id: bytes
    opened_slot: int
    deposit: int
    authorized_cumulative: int
    settled: int
    close_requested_at: int
    grace_seconds: int
    status: str


def parse_channel(address: str, data: bytes) -> OnchainChannel:
    if len(data) != 247 or data[:8] != DISCRIMINATOR:
        raise ValueError("invalid ChannelAccount data")
    o = 8

    def pubkey() -> str:
        nonlocal o
        value = str(Pubkey.from_bytes(data[o : o + 32]))
        o += 32
        return value

    payer = pubkey()
    payee = pubkey()
    mint = pubkey()
    vault = pubkey()
    signer = data[o : o + 32]
    o += 32
    channel_id = data[o : o + 32]
    o += 32
    opened_slot, deposit, authorized, settled = struct.unpack_from("<QQQQ", data, o)
    o += 32
    (close_requested_at,) = struct.unpack_from("<q", data, o)
    o += 8
    (grace_seconds,) = struct.unpack_from("<I", data, o)
    o += 4
    status = {0: "open", 1: "closing"}.get(data[o], f"unknown({data[o]})")
    return OnchainChannel(
        address=address,
        payer=payer,
        payee=payee,
        mint=mint,
        vault=vault,
        authorized_signer=signer,
        channel_id=channel_id,
        opened_slot=opened_slot,
        deposit=deposit,
        authorized_cumulative=authorized,
        settled=settled,
        close_requested_at=close_requested_at,
        grace_seconds=grace_seconds,
        status=status,
    )


async def fetch_channel(address: str) -> OnchainChannel | None:
    """Fetch a channel and reject accounts not owned by this program."""
    pubkey = Pubkey.from_string(address)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            RPC,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    str(pubkey),
                    {"encoding": "base64", "commitment": "confirmed"},
                ],
            },
        )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(
            f"Solana RPC error: {payload['error'].get('message', 'unknown')}"
        )
    value = payload.get("result", {}).get("value")
    if value is None:
        return None
    if value.get("owner") != str(PROGRAM_ID):
        raise ValueError("channel account is not owned by the configured program")
    return parse_channel(address, base64.b64decode(value["data"][0]))
