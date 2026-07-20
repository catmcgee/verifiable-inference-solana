"""pricing.py (ADDON step 4): harness JSONL -> derived USDC prices -> models.yaml.

price_out per 1M tok = (box_$/hr / (tok_s * 3600)) * 1e6 * (1+margin) + receipt amortization
price_in = input_price_fraction * price_out
Prices are GENERATED — hand-editing models.yaml prices is a bug.

Usage: uv run python report/pricing.py [runs/legA-full.jsonl ...]
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from report.analysis import discard_request_warmups

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "models.yaml"
CONFIG = ROOT / "report" / "pricing-config.yaml"


def measured_tok_s(paths: list[Path]) -> dict[str, float]:
    by: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    records = []
    for p in paths:
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
    retained, _ = discard_request_warmups(records)
    for r in retained:
        if r.get("leg") != "A" or r.get("concurrency") != 1:
            continue
        by[r["model"]][r.get("threads", 0)].append(r["tokens_per_s"])
    best: dict[str, float] = {}
    for model, threads in by.items():
        per_t = {t: statistics.median(v) for t, v in threads.items() if v}
        if per_t:
            best[model] = max(per_t.values())  # best measured thread count
    return best


def main(run_files: list[str]) -> None:
    cfg = yaml.safe_load(CONFIG.read_text())
    tok_s = measured_tok_s([Path(f) for f in run_files])
    entries = yaml.safe_load(REGISTRY.read_text())
    # receipts amortized per 1M output tokens at ~128 tok/request
    receipt_per_1m = cfg["receipt_usd"] * (1_000_000 / 128)
    changed = []
    for e in entries:
        ts = tok_s.get(e["id"])
        if not ts:
            continue
        raw = cfg["box_usd_per_hr"] / (ts * 3600) * 1_000_000
        out_price = round(raw * (1 + cfg["margin"]) + receipt_per_1m, 4)
        in_price = round(out_price * cfg["input_price_fraction"], 4)
        e["price_per_1m_out_usdc"] = out_price
        e["price_per_1m_in_usdc"] = in_price
        changed.append((e["id"], ts, in_price, out_price))
    header = REGISTRY.read_text().split("\n\n")[0]  # keep leading comment block
    REGISTRY.write_text(
        header + "\n\n" + yaml.dump(entries, sort_keys=False, allow_unicode=True)
    )
    for mid, ts, ip, op in changed:
        print(f"{mid:<12} {ts:>8.1f} tok/s -> in ${ip}/1M  out ${op}/1M")
    if not changed:
        print("no models priced (no matching leg-A conc-1 records found)")


if __name__ == "__main__":
    main(sys.argv[1:] or [str(ROOT / "runs" / "legA-mini.jsonl")])
