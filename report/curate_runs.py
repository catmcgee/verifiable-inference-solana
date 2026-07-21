#!/usr/bin/env python3
"""Build the report's auditable request set from complete raw artifacts.

Historical SEV-ES and host sweeps remain useful. Partial matched-twin/SNP rows
and the old Leg C probe are replaced by the completed matrices listed below.
Every input is validated against the frozen request schema before an atomic
write; duplicate run IDs fail closed.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
SCHEMA = json.loads((ROOT / "harness" / "schema.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
BASE = RUNS / "real-requests.jsonl"
COMPLETE = {
    "legA-snp-twin-full.jsonl": 320,
    "legB-snp-single-full.jsonl": 160,
    "legB-snp-concurrency-isolated.jsonl": 160,
    "legB-snp-hpke-bound.jsonl": 40,
    "glm-snp-route.jsonl": 10,
    "legC-full.jsonl": 128,
}


def load(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for index, row in enumerate(rows, 1):
        errors = sorted(VALIDATOR.iter_errors(row), key=lambda error: list(error.path))
        if errors:
            raise ValueError(f"{path}:{index}: {errors[0].message}")
    ids = [row["run_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate run_id within raw artifact")
    return rows


def retain_historical(row: dict) -> bool:
    if row["leg"] in ("C-direct", "C-proxied"):
        return False
    if row["leg"] in ("A", "B") and row["numa_policy"] == "guest-single-numa":
        return False
    return True


def main() -> None:
    historical = [row for row in load(BASE) if retain_historical(row)]
    complete = []
    for name, expected in COMPLETE.items():
        path = RUNS / name
        rows = load(path)
        if len(rows) != expected:
            raise ValueError(f"{path}: expected {expected} rows, found {len(rows)}")
        complete.extend(rows)

    curated = sorted(historical + complete, key=lambda row: (row["ts"], row["run_id"]))
    ids = [row["run_id"] for row in curated]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate run_id across curated artifacts")

    temporary = BASE.with_suffix(".jsonl.tmp")
    temporary.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in curated)
    )
    temporary.replace(BASE)
    print(
        f"wrote {BASE}: {len(historical)} historical + {len(complete)} complete "
        f"= {len(curated)} schema-valid unique rows"
    )


if __name__ == "__main__":
    main()
