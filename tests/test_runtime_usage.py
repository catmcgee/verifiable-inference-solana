import time
import unittest
import base64
from unittest.mock import AsyncMock, patch

from server.main import _generate
from server.runtimes.llamacpp import _finish_chat, _validated_usage
from server.receipts.solana import attestation_pda


class LlamaUsageTests(unittest.TestCase):
    def test_validates_complete_usage(self):
        usage = {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
        self.assertEqual(_validated_usage(usage), usage)

    def test_rejects_missing_or_inconsistent_usage(self):
        for usage in (
            {},
            {"prompt_tokens": 1, "completion_tokens": 1},
            {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 99},
            {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2},
        ):
            with self.subTest(usage=usage), self.assertRaises(RuntimeError):
                _validated_usage(usage)

    def test_empty_text_completion_is_valid(self):
        result = _finish_chat(
            time.perf_counter() - 0.01,
            [],
            "",
            {},
            {"prompt_tokens": 7, "completion_tokens": 1, "total_tokens": 8},
            "stop",
        )
        self.assertEqual(result["text"], "")
        self.assertIsNone(result["metrics"]["ttft_ms"])
        self.assertEqual(result["metrics"]["output_tokens"], 1)
        self.assertEqual(result["usage"]["prompt_tokens"], 7)

    def test_usage_count_replaces_stream_chunk_count(self):
        start = time.perf_counter() - 0.02
        result = _finish_chat(
            start,
            [start + 0.005, start + 0.01],
            "several tokens in two chunks",
            {},
            {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
            "length",
        )
        self.assertEqual(result["metrics"]["output_tokens"], 6)
        self.assertEqual(result["finish_reason"], "length")

    def test_engine_token_rate_replaces_text_chunk_rate(self):
        start = time.perf_counter() - 0.02
        result = _finish_chat(
            start,
            [start + 0.005],
            "one text chunk",
            {"predicted_per_second": 15.623942},
            {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            "stop",
        )
        self.assertEqual(result["metrics"]["tokens_per_s"], 15.624)


class SolanaAddressTests(unittest.TestCase):
    def test_attestation_pda_is_deterministic(self):
        key = base64.b64encode(bytes(range(32))).decode()
        self.assertEqual(attestation_pda(key), attestation_pda(key))
        self.assertNotEqual(
            attestation_pda(key), attestation_pda(base64.b64encode(bytes(32)).decode())
        )

    def test_attestation_pda_rejects_wrong_key_length(self):
        with self.assertRaises(ValueError):
            attestation_pda(base64.b64encode(b"short").decode())


class RawGenerationUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_generation_counts_real_prompt_tokens(self):
        runtime = type(
            "Runtime",
            (),
            {
                "generate": AsyncMock(
                    return_value={
                        "text": "ok",
                        "metrics": {"output_tokens": 2},
                    }
                ),
                "tokenize": AsyncMock(return_value=[1, 2, 3]),
            },
        )()
        with (
            patch("server.main._servable"),
            patch("server.main.runtimes.for_model", return_value=runtime),
        ):
            result = await _generate("bitnet-2b", "synthetic prompt", 8)

        self.assertEqual(
            result["usage"],
            {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        )


if __name__ == "__main__":
    unittest.main()
