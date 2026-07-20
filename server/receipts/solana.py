"""One Solana configuration, PDA derivation, RPC reader, and account parser."""

from __future__ import annotations

import base64
import hashlib
import os
import struct

import httpx
from solders.pubkey import Pubkey


PROGRAM_ID = Pubkey.from_string(
    os.environ.get(
        "VINFER_SOLANA_PROGRAM", "Dp5LxL9XHZUVXK129rxwBafqHMg1Y29Zda2svx8vXEkx"
    )
)
RPC_URL = os.environ.get("VINFER_SOLANA_RPC", "https://api.devnet.solana.com")


def attestation_address(enclave_pubkey: bytes) -> Pubkey:
    if len(enclave_pubkey) != 32:
        raise ValueError("enclave Ed25519 public key must be 32 bytes")
    return Pubkey.find_program_address([b"attestation", enclave_pubkey], PROGRAM_ID)[0]


def attestation_pda(enclave_pubkey_b64: str) -> str:
    return str(
        attestation_address(base64.b64decode(enclave_pubkey_b64, validate=True))
    )


def receipt_pda(enclave_pubkey: bytes, index: int) -> Pubkey:
    if len(enclave_pubkey) != 32:
        raise ValueError("enclave Ed25519 public key must be 32 bytes")
    return Pubkey.find_program_address(
        [b"receipt", enclave_pubkey, struct.pack("<Q", index)], PROGRAM_ID
    )[0]


def _get_account(address: Pubkey) -> bytes | None:
    response = httpx.post(
        RPC_URL,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [
                str(address),
                {"encoding": "base64", "commitment": "confirmed"},
            ],
        },
        timeout=30,
    )
    response.raise_for_status()
    value = response.json().get("result", {}).get("value")
    return base64.b64decode(value["data"][0]) if value else None


def parse_attestation(data: bytes) -> dict:
    expected = hashlib.sha256(b"account:AttestationAccount").digest()[:8]
    if len(data) < 215 or data[:8] != expected:
        raise ValueError("invalid AttestationAccount data")
    offset = 8
    enclave = data[offset : offset + 32]
    offset += 32
    measurement = data[offset : offset + 48]
    offset += 48
    report_data = data[offset : offset + 32]
    offset += 32
    model_hash = data[offset : offset + 32]
    offset += 32
    binding_version = data[offset]
    offset += 1
    registry_hash = data[offset : offset + 32]
    offset += 32
    (runtime_length,) = struct.unpack_from("<I", data, offset)
    offset += 4
    if runtime_length > 64 or offset + runtime_length + 26 > len(data):
        raise ValueError("invalid AttestationAccount runtime_version length")
    runtime_version = data[offset : offset + runtime_length].decode()
    offset += runtime_length
    grade = data[offset]
    offset += 1
    slot, receipt_count, _reserved = struct.unpack_from("<QQQ", data, offset)
    return {
        "snp_measurement": measurement.hex(),
        "report_data_hash": report_data.hex(),
        "model_weights_hash": model_hash.hex(),
        "runtime_version": runtime_version,
        "enclave_pubkey": enclave.hex(),
        "attestation_grade": {0: "snp", 1: "launch-only", 2: "none"}.get(
            grade, f"unknown({grade})"
        ),
        "slot": slot,
        "receipt_count": receipt_count,
        "binding_version": binding_version,
        "registry_hash": registry_hash.hex(),
    }


def parse_receipt(data: bytes) -> dict:
    expected = hashlib.sha256(b"account:ReceiptAccount").digest()[:8]
    if len(data) < 161 or data[:8] != expected:
        raise ValueError("invalid ReceiptAccount data")
    offset = 8
    enclave = data[offset : offset + 32]
    offset += 32
    prompt_hash = data[offset : offset + 32]
    offset += 32
    response_hash = data[offset : offset + 32]
    offset += 32
    model_hash = data[offset : offset + 32]
    offset += 32
    timestamp, index, slot = struct.unpack_from("<qQQ", data, offset)
    offset += 24
    return {
        "enclave_pubkey": enclave.hex(),
        "prompt_hash": prompt_hash.hex(),
        "response_hash": response_hash.hex(),
        "model_hash": model_hash.hex(),
        "timestamp": timestamp,
        "index": index,
        "slot": slot,
        "bump": data[offset],
    }


def check_onchain(enclave_pubkey: bytes) -> dict | None:
    data = _get_account(attestation_address(enclave_pubkey))
    return parse_attestation(data) if data is not None else None


def check_receipt(enclave_pubkey: bytes, index: int) -> dict | None:
    data = _get_account(receipt_pda(enclave_pubkey, index))
    return parse_receipt(data) if data is not None else None
