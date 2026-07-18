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


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("VINFER_AUTH_TOKEN")
    return {"authorization": f"Bearer {token}"} if token else {}


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
    attest_fetch_ms = 0.0
    attest_verify_ms = 0.0
    if cell.get("input_mode", "tls") == "hpke":
        from cli.attest_verify import verify_attestation
        from server.crypto.hpke_box import seal_to_enclave

        t0 = time.perf_counter()
        att_response = client.get(f"{base_url}/v1/attestation", timeout=60)
        att_response.raise_for_status()
        attestation = att_response.json()
        attest_fetch_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        verdict = verify_attestation(attestation)
        attest_verify_ms = (time.perf_counter() - t0) * 1000
        if not verdict.trusted:
            raise RuntimeError(f"refusing HPKE benchmark: {verdict.reason}")
        box = seal_to_enclave(attestation["hpke_public_key_b64"], prompt.encode())
        r = client.post(
            f"{base_url}/v1/infer_sealed",
            json={
                "model": cell["model"],
                "enc": box["enc"],
                "ciphertext": box["ciphertext"],
                "max_tokens": cell["output_tokens"],
            },
            timeout=600,
        )
    else:
        r = client.post(
            f"{base_url}/v1/infer",
            json={
                "model": cell["model"],
                "prompt": prompt,
                "max_tokens": cell["output_tokens"],
            },
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
        "attest_fetch_ms": round(attest_fetch_ms, 3),
        "attest_verify_ms": round(attest_verify_ms, 3),
        "receipt_sign_ms": m.get("receipt_sign_ms", 0),
        "receipt_post_ms": m.get("receipt_post_ms", 0),
        "receipt_confirm_ms": m.get("receipt_confirm_ms", 0),
        "solana_cu": m.get("solana_cu", 0),
        "solana_fee_lamports": m.get("solana_fee_lamports", 0),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    VALIDATOR.validate(record)
    return record


def run(matrix_path: str, out_path: str, base_url: str | None = None) -> dict:
    cfg = json.loads(Path(matrix_path).read_text())
    base_url = (
        base_url
        or cfg.get("base_url")
        or os.environ.get("VINFER_URL", "http://127.0.0.1:8477")
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = cfg.get("n_per_cell", 10)

    done = existing_run_ids(out)
    cells = expand_matrix(cfg)
    todo = {
        cell_run_id(cell, i)
        for cell in cells
        for i in range(n)
        if cell_run_id(cell, i) not in done
    }
    written = 0
    with httpx.Client(headers=_auth_headers()) as client, out.open("a") as f:
        # A cell is an isolation boundary: adjacent models/prompt shapes must
        # never overlap and compete for the host's shared memory bandwidth.
        for cell in cells:
            group = [
                (cell, cell_run_id(cell, i))
                for i in range(n)
                if cell_run_id(cell, i) in todo
            ]
            if not group:
                continue
            conc = cell.get("concurrency", 1)
            with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as pool:
                futures = [
                    pool.submit(one_request, client, base_url, cell, rid)
                    for cell, rid in group
                ]
                for fut in concurrent.futures.as_completed(futures):
                    f.write(json.dumps(fut.result(), sort_keys=True) + "\n")
                    f.flush()
                    written += 1
    relevant = len(cells) * n
    return {
        "cells": len(cells),
        "requested": len(todo),
        "written": written,
        "skipped_resume": relevant - len(todo),
        "out": str(out),
    }


if __name__ == "__main__":
    import sys

    print(json.dumps(run(sys.argv[1], sys.argv[2]), indent=2))
