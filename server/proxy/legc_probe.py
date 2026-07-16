"""Leg C probe: measure Claude API direct latency (streaming), schema-valid JSONL.

Frugal by design — this spends real money. Reads ANTHROPIC_API_KEY from env
(.env.local). Records leg=C-direct rows; the proxy path (C-proxied) reuses this
timing harness through the CVM proxy in P4.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jsonschema

HERE = Path(__file__).resolve().parents[2] / "harness"
VALIDATOR = jsonschema.Draft202012Validator(json.loads((HERE / "schema.json").read_text()))
API = "https://api.anthropic.com/v1/messages"


def measure(api_key: str, model: str, prompt: str, max_tokens: int, run_id: str) -> dict:
    t0 = time.perf_counter()
    tok_times: list[float] = []
    usage = {}
    with httpx.Client(timeout=120) as c:
        with c.stream(
            "POST", API,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "stream": True,
                  "messages": [{"role": "user", "content": prompt}]},
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                ev = json.loads(line[6:])
                if ev.get("type") == "content_block_delta":
                    tok_times.append(time.perf_counter())
                elif ev.get("type") == "message_delta":
                    usage = ev.get("usage", {})
    if not tok_times:
        raise RuntimeError("no stream deltas")
    ttft = (tok_times[0] - t0) * 1000.0
    itls = [(tok_times[i] - tok_times[i - 1]) * 1000.0 for i in range(1, len(tok_times))] or [0.0]
    it = sorted(itls)
    e2e = (tok_times[-1] - t0) * 1000.0
    n_out = usage.get("output_tokens", len(tok_times))
    rec = {
        "run_id": run_id, "leg": "C-direct", "model": model, "quant": "api",
        "sev_mode": "off", "input_mode": "tls", "threads": 0, "numa_policy": "n/a",
        "prompt_tokens": usage.get("input_tokens", 0), "output_tokens": n_out,
        "batch": 1, "concurrency": 1,
        "ttft_ms": round(ttft, 3), "itl_ms_p50": round(it[len(it)//2], 3),
        "itl_ms_p99": round(it[min(len(it)-1, int(len(it)*0.99))], 3),
        "tokens_per_s": round((len(tok_times)-1)/((tok_times[-1]-tok_times[0]) or 1), 3),
        "e2e_ms": round(e2e, 3), "attest_fetch_ms": 0, "attest_verify_ms": 0,
        "receipt_sign_ms": 0, "receipt_post_ms": 0, "receipt_confirm_ms": 0,
        "solana_cu": 0, "solana_fee_lamports": 0,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    VALIDATOR.validate(rec)
    rec["_usage"] = usage  # for spend accounting, stripped before writing
    return rec


if __name__ == "__main__":
    import sys
    key = os.environ["ANTHROPIC_API_KEY"]
    model = os.environ.get("VINFER_C_MODEL", "claude-haiku-4-5-20251001")
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/legC-probe.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    n = int(os.environ.get("VINFER_C_N", "3"))
    cells = [(128, 128), (128, 512)]
    in_tok = out_tok = 0
    with out.open("w") as f:
        for pt, ot in cells:
            for i in range(n):
                rid = f"C{pt}-{ot}-{i}"
                rec = measure(key, model, "Explain memory-bandwidth-bound inference in two sentences.", ot, rid)
                u = rec.pop("_usage")
                in_tok += u.get("input_tokens", 0)
                out_tok += u.get("output_tokens", 0)
                f.write(json.dumps(rec, sort_keys=True) + "\n")
                print(f"{rid}: ttft {rec['ttft_ms']}ms {rec['tokens_per_s']} tok/s e2e {rec['e2e_ms']}ms")
    # Haiku 4.5 pricing: $1/$5 per Mtok in/out
    cost = in_tok/1e6*1.0 + out_tok/1e6*5.0
    print(f"\nleg C probe: {in_tok} in + {out_tok} out tokens ≈ ${cost:.4f} on {model}")
