from __future__ import annotations

import hashlib
import base64
import json
import struct
import unittest
from pathlib import Path

from nacl.signing import SigningKey

from cli.attest_verify import (
    _verify_hpke_binding,
    _verify_snp_policy,
    verify_attestation,
)
from server.receipts.solana import parse_attestation, parse_receipt
from server.receipts.signer import HPKE_BINDING_DOMAIN


ROOT = Path(__file__).resolve().parents[1]


class SnpPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads((ROOT / "attestation-policy.json").read_text())
        self.measurement = bytes.fromhex(self.policy["allowed_measurements"][0])
        self.report = bytearray(0x4A0)
        struct.pack_into("<I", self.report, 0x00, 5)
        struct.pack_into("<Q", self.report, 0x08, 0x30000)
        struct.pack_into("<I", self.report, 0x30, 0)
        struct.pack_into("<I", self.report, 0x34, 1)
        self.report[0x90:0xC0] = self.measurement
        self.report[0x180:0x188] = bytes([0, 1, 0, 2, 0, 0, 0, 71])
        self.doc = {
            "snp_measurement": self.measurement.hex(),
            "server_build_hash": self.policy["allowed_server_build_hashes"][0],
            "execution": {"mode": "guest-declared", "manifest": None},
        }

    def test_allows_pinned_measurement_vmpl0_and_build(self) -> None:
        ok, why = _verify_snp_policy(bytes(self.report), self.doc, self.policy)
        self.assertTrue(ok, why)

    def test_rejects_vmpl1(self) -> None:
        struct.pack_into("<I", self.report, 0x30, 1)
        ok, why = _verify_snp_policy(bytes(self.report), self.doc, self.policy)
        self.assertFalse(ok)
        self.assertIn("VMPL 1", why)

    def test_rejects_unapproved_measurement(self) -> None:
        self.report[0x90:0xC0] = bytes(48)
        ok, why = _verify_snp_policy(bytes(self.report), self.doc, self.policy)
        self.assertFalse(ok)
        self.assertIn("unapproved", why)

    def test_rejects_unapproved_build(self) -> None:
        self.doc["server_build_hash"] = bytes(32).hex()
        ok, why = _verify_snp_policy(bytes(self.report), self.doc, self.policy)
        self.assertFalse(ok)
        self.assertIn("build hash", why)


class ReceiptParserTests(unittest.TestCase):
    def test_parses_anchor_receipt_account(self) -> None:
        discriminator = hashlib.sha256(b"account:ReceiptAccount").digest()[:8]
        enclave = bytes(range(32))
        prompt = bytes([1]) * 32
        response = bytes([2]) * 32
        model = bytes([3]) * 32
        raw = b"".join(
            [
                discriminator,
                enclave,
                prompt,
                response,
                model,
                struct.pack("<qQQB", 1_700_000_000, 7, 42, 254),
            ]
        )

        parsed = parse_receipt(raw)

        self.assertEqual(parsed["enclave_pubkey"], enclave.hex())
        self.assertEqual(parsed["prompt_hash"], prompt.hex())
        self.assertEqual(parsed["response_hash"], response.hex())
        self.assertEqual(parsed["model_hash"], model.hex())
        self.assertEqual(parsed["timestamp"], 1_700_000_000)
        self.assertEqual(parsed["index"], 7)
        self.assertEqual(parsed["slot"], 42)
        self.assertEqual(parsed["bump"], 254)

    def test_rejects_wrong_discriminator(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid ReceiptAccount"):
            parse_receipt(bytes(161))

    def test_attestation_rejects_wrong_discriminator(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid AttestationAccount"):
            parse_attestation(bytes(279))


class HpkeBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.signer = SigningKey.generate()
        self.hpke_key = bytes(range(32))
        signature = self.signer.sign(HPKE_BINDING_DOMAIN + self.hpke_key).signature
        self.doc = {
            "enclave_pubkey_b64": base64.b64encode(
                bytes(self.signer.verify_key)
            ).decode(),
            "hpke_public_key_b64": base64.b64encode(self.hpke_key).decode(),
            "hpke_binding_signature_b64": base64.b64encode(signature).decode(),
        }

    def test_accepts_signed_hpke_key(self) -> None:
        ok, why = _verify_hpke_binding(self.doc)
        self.assertTrue(ok, why)

    def test_rejects_substituted_hpke_key(self) -> None:
        self.doc["hpke_public_key_b64"] = base64.b64encode(bytes(32)).decode()
        ok, why = _verify_hpke_binding(self.doc)
        self.assertFalse(ok)
        self.assertIn("invalid", why)

    def test_malformed_attestation_fails_closed(self) -> None:
        verdict = verify_attestation({"grade": "snp", "enclave_pubkey_b64": "%%%"})
        self.assertFalse(verdict.trusted)
        self.assertFalse(verdict.binding_ok)
        self.assertIn("malformed", verdict.reason)

    def test_non_hpke_component_can_skip_hpke_binding(self) -> None:
        registry_hash = hashlib.sha256(b"proxy-policy").digest()
        build_hash = bytes.fromhex("40" * 32)
        pubkey = bytes(self.signer.verify_key)
        doc = {
            "grade": "none",
            "binding_version": 2,
            "enclave_pubkey_b64": base64.b64encode(pubkey).decode(),
            "registry_hash": registry_hash.hex(),
            "server_build_hash": build_hash.hex(),
            "report_data": hashlib.sha256(
                pubkey + registry_hash + build_hash
            ).hexdigest(),
        }

        required = verify_attestation(doc, allow_unattested=True)
        component = verify_attestation(doc, allow_unattested=True, require_hpke=False)

        self.assertFalse(required.trusted)
        self.assertTrue(component.trusted, component.reason)
        self.assertIn("does not expose an HPKE key", component.reason)

    def test_legacy_binding_uses_model_hash(self) -> None:
        pubkey = bytes(self.signer.verify_key)
        model_hash = bytes.fromhex("20" * 32)
        build_hash = bytes.fromhex("40" * 32)
        doc = {
            "grade": "none",
            "binding_version": 1,
            "enclave_pubkey_b64": base64.b64encode(pubkey).decode(),
            "model_weights_hash": model_hash.hex(),
            "server_build_hash": build_hash.hex(),
            "report_data": hashlib.sha256(
                pubkey + model_hash + build_hash
            ).hexdigest(),
        }

        verdict = verify_attestation(
            doc, allow_unattested=True, require_hpke=False
        )
        self.assertTrue(verdict.trusted, verdict.reason)


if __name__ == "__main__":
    unittest.main()
