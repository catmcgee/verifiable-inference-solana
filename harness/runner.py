"""Experiment runner: matrix config → requests → schema-valid JSONL. Resumable.

run_id is a deterministic hash of (cell, repeat index), so re-running the same
matrix skips completed work by scanning the output file first.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import itertools
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jsonschema

HERE = Path(__file__).parent
SCHEMA = json.loads((HERE / "schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)


def expand_matrix(cfg: dict) -> list[dict]:
    grid = cfg["grid"]
    keys = sorted(grid)
    cells = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        cells.append(dict(zip(keys, combo)))
    return cells


def cell_run_id(cell: dict, idx: int) -> str:
    payload = json.dumps({"cell": cell, "idx": idx}, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


def existing_run_ids(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    ids = set()
    with out_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                ids.add(json.loads(line)["run_id"])
    return ids


def one_request(client: httpx.Client, base_url: str, cell: dict, run_id: str) -> dict:
    prompt = "measure " * max(1, cell["prompt_tokens"])  # benchmark filler (token≈word)
    r = client.post(
        f"{base_url}/v1/infer",
        json={"model": cell["model"], "prompt": prompt, "max_tokens": cell["output_tokens"]},
        timeout=600,
    )
    r.raise_for_status()
    body = r.json()
    m = body["metrics"]
    record = {
        "run_id": run_id,
        "leg": cell["leg"],
        "model": cell["model"],
        "quant": cell.get("quant", ""),
        "sev_mode": m.get("sev_mode", "off"),
        "input_mode": cell.get("input_mode", "tls"),
        "threads": cell.get("threads", 0),
        "numa_policy": cell.get("numa_policy", "default"),
        "prompt_tokens": cell["prompt_tokens"],
        "output_tokens": m["output_tokens"],
        "batch": cell.get("batch", 1),
        "concurrency": cell.get("concurrency", 1),
        "ttft_ms": m["ttft_ms"],
        "itl_ms_p50": m["itl_ms_p50"],
        "itl_ms_p99": m["itl_ms_p99"],
        "tokens_per_s": m["tokens_per_s"],
        "e2e_ms": m["e2e_ms"],
        "attest_fetch_ms": 0,
        "attest_verify_ms": 0,
        "receipt_sign_ms": m.get("receipt_sign_ms", 0),
        "receipt_post_ms": 0,
        "receipt_confirm_ms": 0,
        "solana_cu": 0,
        "solana_fee_lamports": 0,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    VALIDATOR.validate(record)
    return record


def run(matrix_path: str, out_path: str, base_url: str | None = None) -> dict:
    cfg = json.loads(Path(matrix_path).read_text())
    base_url = base_url or cfg.get("base_url") or os.environ.get("VINFER_URL", "http://127.0.0.1:8477")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = cfg.get("n_per_cell", 10)

    done = existing_run_ids(out)
    cells = expand_matrix(cfg)
    todo = [
        (cell, cell_run_id(cell, i))
        for cell in cells
        for i in range(n)
        if cell_run_id(cell, i) not in done
    ]
    written = 0
    with httpx.Client() as client, out.open("a") as f:
        # group by concurrency so each cell runs at its own request parallelism
        for conc, group in itertools.groupby(
            sorted(todo, key=lambda t: t[0].get("concurrency", 1)),
            key=lambda t: t[0].get("concurrency", 1),
        ):
            group = list(group)
            with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as pool:
                futures = [
                    pool.submit(one_request, client, base_url, cell, rid) for cell, rid in group
                ]
                for fut in concurrent.futures.as_completed(futures):
                    f.write(json.dumps(fut.result(), sort_keys=True) + "\n")
                    f.flush()
                    written += 1
    return {"cells": len(cells), "requested": len(todo), "written": written, "skipped_resume": len(done), "out": str(out)}


if __name__ == "__main__":
    import sys

    print(json.dumps(run(sys.argv[1], sys.argv[2]), indent=2))
