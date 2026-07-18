"""Deterministic Solana addresses attached to off-chain signed receipts."""

from __future__ import annotations

import base64
import os

from solders.pubkey import Pubkey


PROGRAM_ID = Pubkey.from_string(
    os.environ.get(
        "VINFER_SOLANA_PROGRAM",
        "Dp5LxL9XHZUVXK129rxwBafqHMg1Y29Zda2svx8vXEkx",
    )
)


def attestation_pda(enclave_pubkey_b64: str) -> str:
    enclave_pubkey = base64.b64decode(enclave_pubkey_b64, validate=True)
    if len(enclave_pubkey) != 32:
        raise ValueError("enclave Ed25519 public key must be 32 bytes")
    address, _ = Pubkey.find_program_address(
        [b"attestation", enclave_pubkey], PROGRAM_ID
    )
    return str(address)
