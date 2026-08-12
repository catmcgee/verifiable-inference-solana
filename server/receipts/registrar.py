"""Register a newly rotated, policy-approved TEE service key on Solana devnet."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import struct
import time
from pathlib import Path

import httpx
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

from cli.attest_verify import verify_attestation
from server.receipts.solana import (
    PROGRAM_ID,
    RPC_URL,
    attestation_address,
    parse_attestation,
)

SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")
REGISTER_DISCRIMINATOR = hashlib.sha256(b"global:register_attestation").digest()[:8]


class RegistrationError(RuntimeError):
    pass


class AttestationRegistrar:
    def __init__(self, payer_path: str | Path, rpc_url: str = RPC_URL) -> None:
        path = Path(payer_path).expanduser()
        if path.stat().st_mode & 0o077:
            raise RegistrationError(f"payer file must be mode 0600: {path}")
        self._payer = Keypair.from_bytes(bytes(json.loads(path.read_text())))
        self._rpc_url = rpc_url
        self._client = httpx.Client(timeout=30)

    def _rpc(self, method: str, params: list) -> dict:
        response = self._client.post(
            self._rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        response.raise_for_status()
        body = response.json()
        if body.get("error"):
            raise RegistrationError(
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
                    raise RegistrationError(
                        f"Solana transaction failed: {status['err']}"
                    )
                if status.get("confirmationStatus") in ("confirmed", "finalized"):
                    return
            time.sleep(0.5)
        raise RegistrationError("Solana confirmation timed out")

    @staticmethod
    def _expected(attestation: dict) -> dict:
        if attestation.get("grade") != "snp":
            raise RegistrationError("only an SNP-grade attestation may be registered")
        if attestation.get("binding_version") != 2:
            raise RegistrationError("only binding version 2 may be registered")
        enclave = base64.b64decode(attestation["enclave_pubkey_b64"], validate=True)
        report = base64.b64decode(attestation["snp_report_b64"], validate=True)
        report_data = bytes.fromhex(attestation["report_data"])
        registry_hash = bytes.fromhex(attestation["registry_hash"])
        runtime = attestation["runtime_version"]
        if len(enclave) != 32 or len(report) < 0xC0:
            raise RegistrationError("attestation key or SNP report has an invalid length")
        if len(report_data) != 32 or len(registry_hash) != 32:
            raise RegistrationError("attestation binding hash has an invalid length")
        if not isinstance(runtime, str) or not runtime or len(runtime.encode()) > 64:
            raise RegistrationError("runtime version is missing or too long")
        return {
            "enclave": enclave,
            "measurement": report[0x90:0xC0],
            "report_data": report_data,
            "registry_hash": registry_hash,
            "runtime": runtime,
        }

    @staticmethod
    def _instruction_data(expected: dict) -> bytes:
        runtime = expected["runtime"].encode()
        return b"".join(
            (
                REGISTER_DISCRIMINATOR,
                expected["enclave"],
                expected["measurement"],
                expected["report_data"],
                bytes(32),  # deprecated single-model hash; v2 uses registry_hash
                struct.pack("<I", len(runtime)),
                runtime,
                b"\x00",  # AttestationGrade::Snp
                b"\x02",  # binding version 2
                expected["registry_hash"],
            )
        )

    @staticmethod
    def _require_exact_account(data: bytes, expected: dict) -> None:
        account = parse_attestation(data)
        wanted = {
            "enclave_pubkey": expected["enclave"].hex(),
            "snp_measurement": expected["measurement"].hex(),
            "report_data_hash": expected["report_data"].hex(),
            "model_weights_hash": bytes(32).hex(),
            "runtime_version": expected["runtime"],
            "attestation_grade": "snp",
            "binding_version": 2,
            "registry_hash": expected["registry_hash"].hex(),
        }
        if any(account[key] != value for key, value in wanted.items()):
            raise RegistrationError("existing attestation PDA differs from live evidence")

    def reconcile(self, attestation: dict) -> dict:
        expected = self._expected(attestation)
        address = attestation_address(expected["enclave"])
        existing = self._account(address)
        if existing is not None:
            self._require_exact_account(existing, expected)
            return {"pda": str(address), "transaction": None, "created": False}

        verdict = verify_attestation(
            attestation, allow_unattested=False, require_hpke=True
        )
        if not verdict.trusted:
            raise RegistrationError(f"attestation is not trusted: {verdict.reason}")

        instruction = Instruction(
            PROGRAM_ID,
            self._instruction_data(expected),
            [
                AccountMeta(self._payer.pubkey(), True, True),
                AccountMeta(address, False, True),
                AccountMeta(SYSTEM_PROGRAM, False, False),
            ],
        )
        latest = self._rpc("getLatestBlockhash", [{"commitment": "confirmed"}])
        transaction = Transaction(
            [self._payer],
            Message([instruction], self._payer.pubkey()),
            Hash.from_string(latest["value"]["blockhash"]),
        )
        signature = self._rpc(
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
        self._confirm(signature)
        created = self._account(address)
        if created is None:
            raise RegistrationError("confirmed transaction created no attestation PDA")
        self._require_exact_account(created, expected)
        return {"pda": str(address), "transaction": signature, "created": True}


def fetch_attestation(url: str) -> dict:
    response = httpx.get(f"{url.rstrip('/')}/v1/attestation", timeout=60)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url", default=os.environ.get("VINFER_URL", "http://127.0.0.1:8479")
    )
    parser.add_argument(
        "--payer",
        default=os.environ.get(
            "VINFER_SOLANA_PAYER", "solana/.devnet-deployer.json"
        ),
    )
    parser.add_argument("--rpc", default=RPC_URL)
    args = parser.parse_args()
    result = AttestationRegistrar(args.payer, args.rpc).reconcile(
        fetch_attestation(args.url)
    )
    action = "registered" if result["created"] else "already registered"
    print(f"{action}: {result['pda']}")
    if result["transaction"]:
        print(f"transaction: {result['transaction']}")


if __name__ == "__main__":
    main()
