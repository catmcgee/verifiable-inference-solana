"""Post an enclave-signed, hash-only receipt to the deployed Solana program."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading
import time
from pathlib import Path

import httpx
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from server.receipts.signer import receipt_message, verify_receipt
from server.receipts.solana import (
    PROGRAM_ID,
    attestation_address,
    parse_attestation,
    parse_receipt,
    receipt_pda,
)

ED25519_PROGRAM = Pubkey.from_string("Ed25519SigVerify111111111111111111111111111")
INSTRUCTIONS_SYSVAR = Pubkey.from_string("Sysvar1nstructions1111111111111111111111111")
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")
POST_RECEIPT_DISCRIMINATOR = hashlib.sha256(b"global:post_receipt").digest()[:8]


class ReceiptPostError(RuntimeError):
    pass


class ReceiptPoster:
    def __init__(self, payer_path: str | Path, rpc_url: str) -> None:
        path = Path(payer_path).expanduser()
        if path.stat().st_mode & 0o077:
            raise ReceiptPostError(f"payer file must be mode 0600: {path}")
        raw = json.loads(path.read_text())
        self._payer = Keypair.from_bytes(bytes(raw))
        self._rpc_url = rpc_url
        self._client = httpx.Client(timeout=30)
        self._lock = threading.Lock()

    def _rpc(self, method: str, params: list) -> dict:
        response = self._client.post(
            self._rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        response.raise_for_status()
        body = response.json()
        if body.get("error"):
            raise ReceiptPostError(
                body["error"].get("message", f"Solana RPC {method} failed")
            )
        return body["result"]

    def _account(self, address: Pubkey) -> bytes | None:
        result = self._rpc(
            "getAccountInfo",
            [str(address), {"encoding": "base64", "commitment": "confirmed"}],
        )
        value = result.get("value")
        return base64.b64decode(value["data"][0]) if value else None

    @staticmethod
    def _ed25519_instruction(
        enclave: bytes, signature: bytes, message: bytes
    ) -> Instruction:
        if len(enclave) != 32 or len(signature) != 64 or len(message) != 104:
            raise ReceiptPostError("invalid Ed25519 receipt field length")
        public_key_offset = 16
        signature_offset = public_key_offset + 32
        message_offset = signature_offset + 64
        data = (
            struct.pack(
                "<BB7H",
                1,
                0,
                signature_offset,
                0xFFFF,
                public_key_offset,
                0xFFFF,
                message_offset,
                len(message),
                0xFFFF,
            )
            + enclave
            + signature
            + message
        )
        return Instruction(ED25519_PROGRAM, data, [])

    def _program_instruction(
        self, receipt: dict, index: int
    ) -> tuple[Instruction, Pubkey]:
        enclave = base64.b64decode(receipt["enclave_pubkey_b64"], validate=True)
        attestation = attestation_address(enclave)
        receipt_address = receipt_pda(enclave, index)
        data = POST_RECEIPT_DISCRIMINATOR + b"".join(
            (
                enclave,
                bytes.fromhex(receipt["prompt_hash"]),
                bytes.fromhex(receipt["response_hash"]),
                bytes.fromhex(receipt["model_hash"]),
                struct.pack("<q", int(receipt["timestamp"])),
            )
        )
        accounts = [
            AccountMeta(self._payer.pubkey(), True, True),
            AccountMeta(attestation, False, True),
            AccountMeta(receipt_address, False, True),
            AccountMeta(INSTRUCTIONS_SYSVAR, False, False),
            AccountMeta(SYSTEM_PROGRAM, False, False),
        ]
        return Instruction(PROGRAM_ID, data, accounts), receipt_address

    def _confirm(self, signature: str, timeout_s: float = 60) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            result = self._rpc(
                "getSignatureStatuses",
                [[signature], {"searchTransactionHistory": True}],
            )
            status = result["value"][0]
            if status:
                if status.get("err") is not None:
                    raise ReceiptPostError(
                        f"Solana transaction failed: {status['err']}"
                    )
                if status.get("confirmationStatus") in ("confirmed", "finalized"):
                    return
            time.sleep(0.5)
        raise ReceiptPostError("Solana confirmation timed out")

    def post(self, receipt: dict) -> dict:
        if not verify_receipt(receipt):
            raise ReceiptPostError("enclave receipt signature is invalid")
        enclave = base64.b64decode(receipt["enclave_pubkey_b64"], validate=True)
        message = receipt_message(
            bytes.fromhex(receipt["prompt_hash"]),
            bytes.fromhex(receipt["response_hash"]),
            bytes.fromhex(receipt["model_hash"]),
            int(receipt["timestamp"]),
        )
        signature = base64.b64decode(receipt["sig_b64"], validate=True)

        with self._lock:
            attestation_pda = attestation_address(enclave)
            attestation_data = self._account(attestation_pda)
            if attestation_data is None:
                raise ReceiptPostError("enclave attestation PDA is absent")
            attestation = parse_attestation(attestation_data)
            if attestation["enclave_pubkey"] != enclave.hex():
                raise ReceiptPostError("attestation PDA enclave key mismatch")
            index = int(attestation["receipt_count"])
            program_ix, receipt_address = self._program_instruction(receipt, index)
            ed25519_ix = self._ed25519_instruction(enclave, signature, message)
            latest = self._rpc("getLatestBlockhash", [{"commitment": "confirmed"}])
            blockhash = Hash.from_string(latest["value"]["blockhash"])
            transaction = Transaction(
                [self._payer],
                Message([ed25519_ix, program_ix], self._payer.pubkey()),
                blockhash,
            )
            post_start = time.perf_counter()
            tx_signature = self._rpc(
                "sendTransaction",
                [
                    base64.b64encode(bytes(transaction)).decode(),
                    {
                        "encoding": "base64",
                        "skipPreflight": False,
                        "preflightCommitment": "confirmed",
                    },
                ],
            )
            post_ms = round((time.perf_counter() - post_start) * 1000, 3)
            confirm_start = time.perf_counter()
            self._confirm(tx_signature)
            confirm_ms = round((time.perf_counter() - confirm_start) * 1000, 3)

            posted_data = self._account(receipt_address)
            if posted_data is None:
                raise ReceiptPostError(
                    "confirmed transaction created no receipt account"
                )
            posted = parse_receipt(posted_data)
            expected = {
                "enclave_pubkey": enclave.hex(),
                "prompt_hash": receipt["prompt_hash"],
                "response_hash": receipt["response_hash"],
                "model_hash": receipt["model_hash"],
                "timestamp": int(receipt["timestamp"]),
                "index": index,
            }
            if any(posted[key] != value for key, value in expected.items()):
                raise ReceiptPostError(
                    "confirmed receipt account differs from signed hashes"
                )

            transaction_meta = self._rpc(
                "getTransaction",
                [
                    tx_signature,
                    {
                        "encoding": "json",
                        "commitment": "confirmed",
                        "maxSupportedTransactionVersion": 0,
                    },
                ],
            )
            meta = transaction_meta.get("meta") if transaction_meta else None
            return {
                "onchain_status": "confirmed",
                "receipt_index": index,
                "receipt_pda": str(receipt_address),
                "receipt_tx": tx_signature,
                "receipt_post_ms": post_ms,
                "receipt_confirm_ms": confirm_ms,
                "solana_cu": meta.get("computeUnitsConsumed", 0) if meta else 0,
                "solana_fee_lamports": meta.get("fee", 0) if meta else 0,
            }
