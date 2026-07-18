from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from server.receipts.relay import RelayReceipt
from server.receipts.request_hash import canonical_request
from server.receipts.signer import EnclaveSigner


class ReceiptPrivacyTests(unittest.TestCase):
    def test_signed_receipt_contains_hashes_not_plaintext(self):
        prompt = "private prompt that must not leave the TEE"
        response = "private response that must not leave the TEE"
        receipt = EnclaveSigner().sign_receipt(prompt, response, bytes(32))
        encoded = json.dumps(receipt)

        self.assertNotIn(prompt, encoded)
        self.assertNotIn(response, encoded)
        self.assertNotIn('"prompt"', encoded)
        self.assertNotIn('"response"', encoded)
        self.assertRegex(receipt["prompt_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(receipt["response_hash"], r"^[0-9a-f]{64}$")

    def test_relay_rejects_plaintext_or_identity_fields(self):
        payload = {
            "receipt_id": "receipt-1",
            "enclave_pubkey_b64": "A" * 44,
            "prompt_hash": "0" * 64,
            "response_hash": "1" * 64,
            "model_hash": "2" * 64,
            "timestamp": 1,
            "sig_b64": "A" * 88,
        }
        for field in ("prompt", "response", "messages", "user_id"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                RelayReceipt.model_validate({**payload, field: "must not pass"})

    def test_canonical_request_preserves_roles_boundaries_and_parameters(self):
        def request(messages: list[dict], max_tokens: int = 8) -> bytes:
            return canonical_request(
                endpoint="openai-chat-completions",
                model="bitnet-2b",
                messages=messages,
                max_tokens=max_tokens,
            )

        base = request(
            [
                {"role": "user", "content": "a"},
                {"role": "assistant", "content": "b"},
            ]
        )
        variants = {
            request([{"role": "user", "content": "a\nb"}]),
            request(
                [
                    {"role": "assistant", "content": "a"},
                    {"role": "user", "content": "b"},
                ]
            ),
            request(
                [
                    {"role": "user", "content": "a"},
                    {"role": "assistant", "content": "b"},
                ],
                max_tokens=9,
            ),
        }
        self.assertEqual(len({base, *variants}), 4)


if __name__ == "__main__":
    unittest.main()
