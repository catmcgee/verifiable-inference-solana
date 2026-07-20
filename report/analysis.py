"""Shared rules used by the single measurements aggregation pipeline."""

from __future__ import annotations

import re
from collections import defaultdict


REQUEST_CELL_FIELDS = (
    "leg",
    "model",
    "quant",
    "sev_mode",
    "input_mode",
    "threads",
    "numa_policy",
    "prompt_tokens",
    "output_tokens",
    "batch",
    "concurrency",
)


def discard_request_warmups(records: list[dict], count: int = 2):
    """Drop early samples per experimental cell without changing raw JSONL."""
    cells = defaultdict(list)
    for record in records:
        key = tuple(record.get(field) for field in REQUEST_CELL_FIELDS)
        if record.get("leg", "").startswith("C-"):
            match = re.fullmatch(
                r"C-(?:direct|proxied)-(\d+)-(\d+)-c(\d+)-(\d+)",
                record["run_id"],
            )
            if match:
                key = tuple(
                    record.get(field)
                    for field in REQUEST_CELL_FIELDS
                    if field != "output_tokens"
                ) + ("requested-output", int(match.group(2)))
        cells[key].append(record)

    retained = []
    discarded = []
    for cell in cells.values():
        ordered = sorted(cell, key=lambda record: (record["ts"], record["run_id"]))
        cut = min(count, max(0, len(ordered) - 1))
        discarded.extend(ordered[:cut])
        retained.extend(ordered[cut:])
    return sorted(retained, key=lambda record: record["ts"]), discarded
