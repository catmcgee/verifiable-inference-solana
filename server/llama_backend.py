"""Real backend: proxies to llama-server instances (llama.cpp / bitnet.cpp).

Selected with VINFER_BACKEND=llama (default remains the mock). Each model maps
to a local llama-server port (started by infra/run-servers.sh on the box).
TTFT/ITL are measured here from the SSE stream — wall clock, not the engine's
self-reported numbers (those are logged too, but the schema records what a
client actually experiences).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import httpx

MODELS_DIR = Path(os.environ.get("VINFER_MODELS_DIR", str(Path.home() / "models")))

# name -> (gguf filename, quant, port). Ports match infra/run-servers.sh.
REAL_MODELS: dict[str, dict] = {
    "bitnet-2b": {"file": "bitnet-b1.58-2B-4T-i2_s.gguf", "quant": "i2_s", "port": 8601},
    "8b-q4": {"file": "llama-3.1-8b-instruct-Q4_K_M.gguf", "quant": "Q4_K_M", "port": 8602},
    "8b-q8": {"file": "llama-3.1-8b-instruct-Q8_0.gguf", "quant": "Q8_0", "port": 8603},
    "70b-q4": {"file": "llama-3.3-70b-instruct-Q4_K_M.gguf", "quant": "Q4_K_M", "port": 8604},
}

SEV_MODE = os.environ.get("VINFER_SEV_MODE", "off")

_hash_cache: dict[str, bytes] = {}


def model_weights_hash(model: str) -> bytes:
    """sha256 of the gguf file (first shard for split models), cached."""
    if model in _hash_cache:
        return _hash_cache[model]
    sums = MODELS_DIR / "SHA256SUMS"
    fname = REAL_MODELS[model]["file"]
    if sums.exists():
        for line in sums.read_text().splitlines():
            if line.strip().endswith(fname):
                _hash_cache[model] = bytes.fromhex(line.split()[0])
                return _hash_cache[model]
    h = hashlib.sha256()
    with (MODELS_DIR / fname).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    _hash_cache[model] = h.digest()
    return _hash_cache[model]


async def generate(model: str, prompt: str, max_tokens: int) -> dict:
    cfg = REAL_MODELS[model]
    url = f"http://127.0.0.1:{cfg['port']}/completion"
    payload = {
        "prompt": prompt,
        "n_predict": max_tokens,
        "stream": True,
        "cache_prompt": False,  # measurement: no cross-request prompt cache
        "temperature": 0.7,
    }
    t_start = time.perf_counter()
    token_times: list[float] = []
    text_parts: list[str] = []
    engine_timings: dict = {}

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = json.loads(line[6:])
                if data.get("content"):
                    token_times.append(time.perf_counter())
                    text_parts.append(data["content"])
                if data.get("stop"):
                    engine_timings = data.get("timings", {})

    if not token_times:
        raise RuntimeError(f"no tokens from llama-server for {model}")

    ttft_ms = (token_times[0] - t_start) * 1000.0
    itls = [
        (token_times[i] - token_times[i - 1]) * 1000.0 for i in range(1, len(token_times))
    ] or [0.0]
    itls_sorted = sorted(itls)
    e2e_ms = (token_times[-1] - t_start) * 1000.0
    n_out = len(token_times)
    gen_s = token_times[-1] - token_times[0]

    return {
        "text": "".join(text_parts),
        "metrics": {
            "ttft_ms": round(ttft_ms, 3),
            "itl_ms_p50": round(itls_sorted[len(itls_sorted) // 2], 3),
            "itl_ms_p99": round(itls_sorted[min(len(itls_sorted) - 1, int(len(itls_sorted) * 0.99))], 3),
            "tokens_per_s": round((n_out - 1) / gen_s, 3) if gen_s > 0 else 0.0,
            "e2e_ms": round(e2e_ms, 3),
            "output_tokens": n_out,
            "sev_mode": SEV_MODE,
            "backend": "llama",
            "engine_timings": engine_timings,
        },
    }
