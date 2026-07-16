"""Mock inference backend — stands in for bitnet.cpp / llama.cpp until P2.

Latency model is parameterized per model with an SEV tax factor so the whole
pipeline (server → harness → JSONL → report) can be exercised locally.
VINFER_MOCK_TIMESCALE compresses simulated time so e2e tests run in seconds;
the *simulated* metrics are reported alongside so records stay plausible.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random

# Mock latency profiles only (NOT model config — that lives in models.yaml).
# Keys must be registry ids; used purely to shape simulated output locally.
MODELS: dict[str, dict] = {
    "bitnet-2b": {"quant": "i2_s", "tok_s": 90.0, "ttft_ms": 120.0, "sev_tax": 0.02},
    "8b-q4": {"quant": "Q4_K_M", "tok_s": 22.0, "ttft_ms": 350.0, "sev_tax": 0.05},
    "8b-q8": {"quant": "Q8_0", "tok_s": 14.0, "ttft_ms": 420.0, "sev_tax": 0.06},
    "70b-q4": {"quant": "Q4_K_M", "tok_s": 3.5, "ttft_ms": 2100.0, "sev_tax": 0.09},
    "glm-5.2-q4": {"quant": "UD-Q4_K_XL", "tok_s": 10.0, "ttft_ms": 1500.0, "sev_tax": 0.08},
}

SEV_MODE = os.environ.get("VINFER_SEV_MODE", "off")  # off|sev|es|snp
TIMESCALE = float(os.environ.get("VINFER_MOCK_TIMESCALE", "0.01"))

LOREM = (
    "attested throughput latency bandwidth enclave measurement receipt ternary "
    "matmul verify proof channel encrypted plaintext token stream"
).split()


def model_weights_hash(model: str) -> bytes:
    # P2 replaces this with the real GGUF file hash
    return hashlib.sha256(f"mock-weights:{model}".encode()).digest()


async def generate(model: str, prompt: str, max_tokens: int) -> dict:
    cfg = MODELS[model]
    rng = random.Random(hash((model, prompt, max_tokens)) & 0xFFFFFFFF)
    tax = cfg["sev_tax"] if SEV_MODE != "off" else 0.0
    tok_s = cfg["tok_s"] * (1.0 - tax) * rng.uniform(0.95, 1.05)
    ttft_ms = cfg["ttft_ms"] * (1.0 + tax) * rng.uniform(0.9, 1.15)

    await asyncio.sleep(ttft_ms / 1000.0 * TIMESCALE)
    itls = []
    words = []
    for i in range(max_tokens):
        itl = 1000.0 / tok_s * rng.uniform(0.85, 1.25)
        itls.append(itl)
        await asyncio.sleep(itl / 1000.0 * TIMESCALE)
        words.append(rng.choice(LOREM))

    itls.sort()
    e2e_ms = ttft_ms + sum(itls)
    return {
        "text": " ".join(words),
        "metrics": {
            "ttft_ms": round(ttft_ms, 3),
            "itl_ms_p50": round(itls[len(itls) // 2], 3) if itls else 0.0,
            "itl_ms_p99": round(itls[min(len(itls) - 1, int(len(itls) * 0.99))], 3) if itls else 0.0,
            "tokens_per_s": round(max_tokens / (sum(itls) / 1000.0), 3) if itls else 0.0,
            "e2e_ms": round(e2e_ms, 3),
            "output_tokens": max_tokens,
            "sev_mode": SEV_MODE,
            "backend": "mock",
        },
    }
