"""llama.cpp runtime adapter: proxies a local llama-server instance.

TTFT/ITL are wall-clock measured here (what a client experiences); the
engine's own timings ride along in metrics.engine_timings.
"""

from __future__ import annotations

import json
import os
import time

import httpx

from server.runtimes.base import Runtime

SEV_MODE = os.environ.get("VINFER_SEV_MODE", "off")


def _finish(t_start: float, token_times: list[float], text: str, engine: dict) -> dict:
    if not token_times:
        raise RuntimeError("no tokens from llama-server")
    itls = [(token_times[i] - token_times[i - 1]) * 1000.0 for i in range(1, len(token_times))] or [0.0]
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


class LlamaCppRuntime(Runtime):
    @property
    def _base(self) -> str:
        return f"http://127.0.0.1:{self.entry.port}"

    async def generate(self, prompt: str, max_tokens: int) -> dict:
        t0 = time.perf_counter()
        times: list[float] = []
        parts: list[str] = []
        engine: dict = {}
        async with httpx.AsyncClient(timeout=None) as c:
            async with c.stream("POST", f"{self._base}/completion", json={
                "prompt": prompt, "n_predict": max_tokens, "stream": True,
                "cache_prompt": False, "temperature": 0.7,
            }) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    d = json.loads(line[6:])
                    if d.get("content"):
                        times.append(time.perf_counter())
                        parts.append(d["content"])
                    if d.get("stop"):
                        engine = d.get("timings", {})
        return _finish(t0, times, "".join(parts), engine)

    async def chat(self, messages: list[dict], max_tokens: int) -> dict:
        # llama-server applies the GGUF's built-in chat template
        t0 = time.perf_counter()
        times: list[float] = []
        parts: list[str] = []
        usage: dict = {}
        async with httpx.AsyncClient(timeout=None) as c:
            async with c.stream("POST", f"{self._base}/v1/chat/completions", json={
                "model": self.entry.id, "messages": messages,
                "max_tokens": max_tokens, "stream": True,
                "stream_options": {"include_usage": True},
            }) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    d = json.loads(line[6:])
                    if d.get("usage"):
                        usage = d["usage"]
                    for ch in d.get("choices", []):
                        delta = ch.get("delta", {}).get("content")
                        if delta:
                            times.append(time.perf_counter())
                            parts.append(delta)
        out = _finish(t0, times, "".join(parts), {})
        out["usage"] = usage
        return out
