import unittest

from pydantic import ValidationError

from server.main import SealedChatRequest
from server.request_validation import (
    ChatRequest,
    MAX_CIPHERTEXT_CHARS,
    MAX_MESSAGES,
    MAX_OUTPUT_TOKENS,
)


class RequestLimitTests(unittest.TestCase):
    def test_chat_requires_bounded_text_messages(self):
        valid = [{"role": "user", "content": "synthetic prompt"}]
        self.assertEqual(ChatRequest(model="bitnet-2b", messages=valid).messages, valid)

        invalid = (
            [],
            [{"role": "tool", "content": "text"}],
            [{"role": "user", "content": {"type": "text"}}],
            [{"role": "user", "content": "x"}] * (MAX_MESSAGES + 1),
        )
        for messages in invalid:
            with self.subTest(messages=len(messages)), self.assertRaises(ValidationError):
                ChatRequest(model="bitnet-2b", messages=messages)

    def test_sealed_ciphertext_is_bounded(self):
        with self.assertRaises(ValidationError):
            SealedChatRequest(
                model="bitnet-2b",
                enc="e",
                ciphertext="x" * (MAX_CIPHERTEXT_CHARS + 1),
            )

    def test_plaintext_and_sealed_chat_share_output_limit(self):
        with self.assertRaises(ValidationError):
            ChatRequest(
                model="bitnet-2b",
                messages=[{"role": "user", "content": "prompt"}],
                max_tokens=MAX_OUTPUT_TOKENS + 1,
            )
        with self.assertRaises(ValidationError):
            SealedChatRequest(
                model="bitnet-2b",
                enc="e",
                ciphertext="c",
                max_tokens=MAX_OUTPUT_TOKENS + 1,
            )


if __name__ == "__main__":
    unittest.main()
