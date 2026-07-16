"""Small pricing subset of the matrix for one model (ADDON checklist step 3).

`make bench MODEL=<id>` -> a handful of leg-A conc-1 requests at the box's
physical-core thread count, appended to runs/pricing/<id>.jsonl. Enough for
pricing.py to derive a price; NOT the headline sweep.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from harness.runner import run

ROOT = Path(__file__).resolve().parents[1]


def main(model_id: str) -> None:
    threads = int(os.environ.get("VINFER_BENCH_THREADS", "64"))
    matrix = {
        "n_per_cell": 8,
        "grid": {
            "leg": ["A"], "model": [model_id],
            "prompt_tokens": [128], "output_tokens": [128],
            "threads": [threads], "concurrency": [1],
            "input_mode": ["tls"], "numa_policy": ["nps1-default"],
        },
    }
    out = ROOT / "runs" / "pricing" / f"{model_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(matrix, f)
        mpath = f.name
    summary = run(mpath, str(out))
    print(json.dumps(summary, indent=2))
    print(f"next: uv run python report/pricing.py {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m harness.pricing_bench <model_id>")
    main(sys.argv[1])
