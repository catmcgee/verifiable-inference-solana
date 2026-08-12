from __future__ import annotations

import base64
import hashlib
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server.receipts.registrar import AttestationRegistrar, RegistrationError


def fixture() -> dict:
    report = bytearray(0x2A0 + 120)
    report[0x90:0xC0] = bytes(range(48))
    return {
        "grade": "snp",
        "binding_version": 2,
        "enclave_pubkey_b64": base64.b64encode(bytes(range(32))).decode(),
        "snp_report_b64": base64.b64encode(report).decode(),
        "report_data": "11" * 32,
        "registry_hash": "22" * 32,
        "runtime_version": "vinfer-test",
    }


class AttestationRegistrarTests(unittest.TestCase):
    def test_instruction_is_canonical_anchor_borsh(self) -> None:
        expected = AttestationRegistrar._expected(fixture())
        data = AttestationRegistrar._instruction_data(expected)
        self.assertEqual(
            data[:8], hashlib.sha256(b"global:register_attestation").digest()[:8]
        )
        offset = 8
        self.assertEqual(data[offset : offset + 32], bytes(range(32)))
        offset += 32
        self.assertEqual(data[offset : offset + 48], bytes(range(48)))
        offset += 48
        self.assertEqual(data[offset : offset + 32], bytes.fromhex("11" * 32))
        offset += 32
        self.assertEqual(data[offset : offset + 32], bytes(32))
        offset += 32
        (runtime_length,) = struct.unpack_from("<I", data, offset)
        offset += 4
        self.assertEqual(data[offset : offset + runtime_length], b"vinfer-test")
        offset += runtime_length
        self.assertEqual(data[offset : offset + 2], b"\x00\x02")
        offset += 2
        self.assertEqual(data[offset:], bytes.fromhex("22" * 32))

    def test_rejects_non_snp_or_legacy_binding(self) -> None:
        attestation = fixture()
        attestation["grade"] = "launch-only"
        with self.assertRaisesRegex(RegistrationError, "SNP-grade"):
            AttestationRegistrar._expected(attestation)
        attestation = fixture()
        attestation["binding_version"] = 1
        with self.assertRaisesRegex(RegistrationError, "version 2"):
            AttestationRegistrar._expected(attestation)

    def test_rejects_invalid_field_lengths(self) -> None:
        attestation = fixture()
        attestation["registry_hash"] = "22"
        with self.assertRaisesRegex(RegistrationError, "invalid length"):
            AttestationRegistrar._expected(attestation)

    def test_missing_pda_fails_closed_before_transaction(self) -> None:
        registrar = object.__new__(AttestationRegistrar)
        registrar._account = lambda _address: None
        registrar._payer = SimpleNamespace(pubkey=lambda: None)
        with (
            patch(
                "server.receipts.registrar.verify_attestation",
                return_value=SimpleNamespace(trusted=False, reason="not approved"),
            ),
            patch.object(registrar, "_rpc") as rpc,
            self.assertRaisesRegex(RegistrationError, "not trusted"),
        ):
            registrar.reconcile(fixture())
        rpc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
