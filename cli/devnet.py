"""Devnet read-path for vinfer verify: registry PDA + receipt PDA checks.

Pure read-only JSON-RPC (httpx) + solders for PDA derivation. Account layout
mirrors the Anchor program (solana/programs/verified_inference/src/state.rs):

AttestationAccount (after 8-byte discriminator), matching state.rs order:
  enclave_ed25519_pubkey [32] | snp_measurement [48] | report_data_hash [32]
  | model_weights_hash [32] | binding_version u8 | registry_hash [32]
  | runtime_version (4-len + bytes) | attestation_grade u8 | slot u64
  | receipt_count u64 | batch_count u64 | bump u8
"""

from __future__ import annotations

import base64
import os
import struct

import httpx
from solders.pubkey import Pubkey

PROGRAM_ID = Pubkey.from_string(
    os.environ.get("VINFER_SOLANA_PROGRAM", "Dp5LxL9XHZUVXK129rxwBafqHMg1Y29Zda2svx8vXEkx")
)
RPC = os.environ.get("VINFER_SOLANA_RPC", "https://api.devnet.solana.com")


def _get_account(pubkey: Pubkey) -> bytes | None:
    r = httpx.post(RPC, json={
        "jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
        "params": [str(pubkey), {"encoding": "base64"}],
    }, timeout=30)
    r.raise_for_status()
    val = r.json().get("result", {}).get("value")
    if val is None:
        return None
    return base64.b64decode(val["data"][0])


def attestation_pda(enclave_pubkey: bytes) -> Pubkey:
    return Pubkey.find_program_address([b"attestation", enclave_pubkey], PROGRAM_ID)[0]


def receipt_pda(enclave_pubkey: bytes, index: int) -> Pubkey:
    return Pubkey.find_program_address(
        [b"receipt", enclave_pubkey, struct.pack("<Q", index)], PROGRAM_ID
    )[0]


def parse_attestation(data: bytes) -> dict:
    o = 8  # anchor discriminator
    enclave = data[o:o+32]; o += 32
    snp_measurement = data[o:o+48]; o += 48
    report_data_hash = data[o:o+32]; o += 32
    model_weights_hash = data[o:o+32]; o += 32
    binding_version = data[o]; o += 1
    registry_hash = data[o:o+32]; o += 32
    (rv_len,) = struct.unpack_from("<I", data, o); o += 4
    runtime_version = data[o:o+rv_len].decode(); o += rv_len
    grade = data[o]; o += 1
    (slot,) = struct.unpack_from("<Q", data, o); o += 8
    (receipt_count,) = struct.unpack_from("<Q", data, o); o += 8
    (batch_count,) = struct.unpack_from("<Q", data, o); o += 8
    return {
        "snp_measurement": snp_measurement.hex(),
        "report_data_hash": report_data_hash.hex(),
        "model_weights_hash": model_weights_hash.hex(),
        "runtime_version": runtime_version,
        "enclave_pubkey": enclave.hex(),
        # Anchor enum order in state.rs: Snp=0, LaunchOnly=1, NoTee=2. Must match
        # exactly — a wrong map once made an on-chain record read the wrong grade.
        # (Discriminant 2 was formerly "mock"; the variant is now the honest
        # NoTee — no TEE — and any legacy PDA at 2 reads as "none".)
        "attestation_grade": {0: "snp", 1: "launch-only", 2: "none"}.get(grade, f"unknown({grade})"),
        "slot": slot,
        "receipt_count": receipt_count,
        "batch_count": batch_count,
        "binding_version": binding_version,
        "registry_hash": registry_hash.hex(),
    }


def check_onchain(enclave_pubkey: bytes) -> dict | None:
    """Fetch and parse the attestation PDA for an enclave key. None if absent."""
    data = _get_account(attestation_pda(enclave_pubkey))
    if data is None:
        return None
    return parse_attestation(data)


def check_receipt(enclave_pubkey: bytes, index: int) -> bool:
    return _get_account(receipt_pda(enclave_pubkey, index)) is not None
