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
BITNET_CHAT_TEMPLATE = """{% set loop_messages = messages %}
{% for message in loop_messages %}
{% set content = message['role'] | capitalize + ': ' + message['content'] | trim + '<|eot_id|>' %}
{{ content }}
{% endfor %}
{% if add_generation_prompt %}{{ 'Assistant: ' }}{% endif %}"""


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
        itls = sorted(
            (token_times[index] - token_times[index - 1]) * 1000.0
            for index in range(1, len(token_times))
        ) or [0.0]
        generation_s = token_times[-1] - token_times[0]
        out = {
            "text": text,
            "metrics": {
                "ttft_ms": round((token_times[0] - t_start) * 1000.0, 3),
                "itl_ms_p50": round(itls[len(itls) // 2], 3),
                "itl_ms_p99": round(
                    itls[min(len(itls) - 1, int(len(itls) * 0.99))], 3
                ),
                "tokens_per_s": round(
                    max(0, usage["completion_tokens"] - 1) / generation_s, 3
                )
                if generation_s > 0
                else 0.0,
                "e2e_ms": round((token_times[-1] - t_start) * 1000.0, 3),
                "output_tokens": usage["completion_tokens"],
                "sev_mode": SEV_MODE,
                "backend": "llama",
                "engine_timings": engine,
            },
        }
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

    def _chat_payload(self, messages: list[dict], max_tokens: int) -> dict:
        payload = {
            "model": self.entry.id,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            # Reasoning-only deltas are not part of OpenAI's portable chat
            # surface. Return visible assistant content consistently.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if self.entry.chat_template == "bitnet":
            payload.update(
                {
                    "chat_template": BITNET_CHAT_TEMPLATE,
                    "temperature": 0.6,
                    "top_p": 0.9,
                    "repeat_penalty": 1.15,
                    "stop": ["<|eot_id|>", "\nUser:", "\nHuman:"],
                }
            )
        return payload

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
