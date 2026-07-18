"""llama.cpp runtime adapter: proxies a local llama-server instance.

TTFT/ITL are wall-clock measured here (what a client experiences); the
engine's own timings ride along in metrics.engine_timings.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import AsyncIterator

import httpx

from server.runtimes.base import Runtime

SEV_MODE = os.environ.get("VINFER_SEV_MODE", "off")


def _finish(t_start: float, token_times: list[float], text: str, engine: dict) -> dict:
    if not token_times:
        raise RuntimeError("no tokens from llama-server")
    itls = [
        (token_times[i] - token_times[i - 1]) * 1000.0
        for i in range(1, len(token_times))
    ] or [0.0]
    it = sorted(itls)
    gen_s = token_times[-1] - token_times[0]
    n = len(token_times)
    return {
        "text": text,
        "metrics": {
            "ttft_ms": round((token_times[0] - t_start) * 1000.0, 3),
            "itl_ms_p50": round(it[len(it) // 2], 3),
            "itl_ms_p99": round(it[min(len(it) - 1, int(len(it) * 0.99))], 3),
            "tokens_per_s": round((n - 1) / gen_s, 3) if gen_s > 0 else 0.0,
            "e2e_ms": round((token_times[-1] - t_start) * 1000.0, 3),
            "output_tokens": n,
            "sev_mode": SEV_MODE,
            "backend": "llama",
            "engine_timings": engine,
        },
    }


def _validated_usage(value: object) -> dict:
    """Return OpenAI token usage only when it is complete and self-consistent."""
    if not isinstance(value, dict):
        raise RuntimeError("llama-server omitted token usage")
    usage = dict(value)
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        count = usage.get(field)
        if type(count) is not int or count < 0:
            raise RuntimeError(f"llama-server returned invalid {field}")
    if usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]:
        raise RuntimeError("llama-server returned inconsistent token usage")
    return usage


def _finish_chat(
    t_start: float,
    token_times: list[float],
    text: str,
    engine: dict,
    usage_value: object,
    finish_reason: str,
) -> dict:
    usage = _validated_usage(usage_value)
    if token_times:
        out = _finish(t_start, token_times, text, engine)
        # Streaming deltas are text chunks, not necessarily one token each.
        out["metrics"]["output_tokens"] = usage["completion_tokens"]
    else:
        out = {
            "text": text,
            "metrics": {
                "ttft_ms": None,
                "itl_ms_p50": None,
                "itl_ms_p99": None,
                "tokens_per_s": 0.0,
                "e2e_ms": round((time.perf_counter() - t_start) * 1000.0, 3),
                "output_tokens": usage["completion_tokens"],
                "sev_mode": SEV_MODE,
                "backend": "llama",
                "engine_timings": engine,
            },
        }
    engine_rate = engine.get("predicted_per_second")
    if (
        usage["completion_tokens"] > 0
        and isinstance(engine_rate, (int, float))
        and math.isfinite(engine_rate)
        and engine_rate >= 0
    ):
        out["metrics"]["tokens_per_s"] = round(engine_rate, 3)
    out["usage"] = usage
    out["finish_reason"] = finish_reason
    return out


class LlamaCppRuntime(Runtime):
    @property
    def _base(self) -> str:
        return f"http://127.0.0.1:{self.entry.port}"

    async def load(self) -> None:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{self._base}/health")
            response.raise_for_status()

    async def tokenize(self, text: str) -> list[int]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._base}/tokenize", json={"content": text, "add_special": True}
            )
            response.raise_for_status()
        tokens = response.json().get("tokens")
        if not isinstance(tokens, list) or not all(
            isinstance(token, int) for token in tokens
        ):
            raise RuntimeError("llama-server returned an invalid tokenize response")
        return tokens

    async def stream_generate(
        self, prompt: str, max_tokens: int
    ) -> AsyncIterator[dict]:
        t0 = time.perf_counter()
        times: list[float] = []
        parts: list[str] = []
        engine: dict = {}
        async with httpx.AsyncClient(timeout=None) as c:
            async with c.stream(
                "POST",
                f"{self._base}/completion",
                json={
                    "prompt": prompt,
                    "n_predict": max_tokens,
                    "stream": True,
                    "cache_prompt": False,
                    "temperature": 0.7,
                },
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    d = json.loads(line[6:])
                    if d.get("content"):
                        times.append(time.perf_counter())
                        parts.append(d["content"])
                        yield {"type": "token", "text": d["content"]}
                    if d.get("stop"):
                        engine = d.get("timings", {})
        yield {"type": "done", "result": _finish(t0, times, "".join(parts), engine)}

    async def chat(self, messages: list[dict], max_tokens: int) -> dict:
        result = None
        async for event in self.chat_stream(messages, max_tokens):
            if event["type"] == "done":
                result = event["result"]
        if result is None:
            raise RuntimeError("llama-server stream ended without final metrics")
        return result

    def _chat_payload(self, messages: list[dict], max_tokens: int) -> dict:
        return {
            "model": self.entry.id,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            # Reasoning-only deltas are not part of OpenAI's portable chat
            # surface. Return visible assistant content consistently.
            "chat_template_kwargs": {"enable_thinking": False},
        }

    async def chat_stream(
        self, messages: list[dict], max_tokens: int
    ) -> AsyncIterator[dict]:
        """Yield text deltas, then one ``done`` event with metrics and usage."""
        # llama-server applies the GGUF's built-in chat template.
        t0 = time.perf_counter()
        times: list[float] = []
        parts: list[str] = []
        usage: dict = {}
        engine: dict = {}
        finish_reason = "stop"
        async with httpx.AsyncClient(timeout=None) as c:
            async with c.stream(
                "POST",
                f"{self._base}/v1/chat/completions",
                json=self._chat_payload(messages, max_tokens),
            ) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    d = json.loads(line[6:])
                    if d.get("usage"):
                        usage = d["usage"]
                    if d.get("timings"):
                        engine = d["timings"]
                    for ch in d.get("choices", []):
                        if ch.get("finish_reason"):
                            finish_reason = ch["finish_reason"]
                        delta = ch.get("delta", {}).get("content")
                        if delta:
                            times.append(time.perf_counter())
                            parts.append(delta)
                            yield {"type": "token", "text": delta}
        out = _finish_chat(t0, times, "".join(parts), engine, usage, finish_reason)
        yield {"type": "done", "result": out}
