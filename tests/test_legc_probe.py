from __future__ import annotations

import unittest

from server.proxy.legc_probe import parse_stream_event


class LegCProbeTests(unittest.TestCase):
    def test_parses_anthropic_and_openai_streams(self) -> None:
        direct_text, direct_usage = parse_stream_event(
            {"type": "content_block_delta", "delta": {"text": "hello"}},
            "C-direct",
        )
        self.assertTrue(direct_text)
        self.assertEqual(direct_usage, {})

        proxy_text, proxy_usage = parse_stream_event(
            {
                "choices": [{"delta": {"content": "hello"}}],
                "usage": {"completion_tokens": 1},
            },
            "C-proxied",
        )
        self.assertTrue(proxy_text)
        self.assertEqual(proxy_usage, {"completion_tokens": 1})


if __name__ == "__main__":
    unittest.main()
