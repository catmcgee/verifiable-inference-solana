#!/usr/bin/env python3
"""Fill legacy empty request ``quant`` values from the model registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server import registry


ROOT = Path(__file__).resolve().parents[1]


def migrate_rows(rows: list[dict], quant_by_model: dict[str, str]) -> int:
    changed = 0
    for row in rows:
        if "quant" not in row or row["quant"]:
            continue
        try:
            row["quant"] = quant_by_model[row["model"]]
        except KeyError as exc:
            raise ValueError(
                f"cannot migrate empty quant for unknown model {row.get('model')!r}"
            ) from exc
        changed += 1
    return changed


def migrate_file(path: Path, quant_by_model: dict[str, str]) -> int:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    changed = migrate_rows(rows, quant_by_model)
    if not changed:
        return 0
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    )
    temporary.replace(path)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    models = registry.load()
    quant_by_model = {model.id: model.quant for model in models.values()}
    paths = args.paths or sorted((ROOT / "runs").glob("*.jsonl"))
    total = 0
    files = 0
    for path in paths:
        changed = migrate_file(path, quant_by_model)
        total += changed
        files += bool(changed)
    print(f"migrated {total} empty quant values across {files} JSONL files")


if __name__ == "__main__":
    main()
