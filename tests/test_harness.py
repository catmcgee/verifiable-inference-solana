from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.runner import run


class HarnessIsolationTests(unittest.TestCase):
    def test_concurrent_workers_never_overlap_matrix_cells(self) -> None:
        active: dict[str, int] = {}
        lock = threading.Lock()

        def request(_client, _base_url, cell, run_id):
            with lock:
                active[cell["model"]] = active.get(cell["model"], 0) + 1
                self.assertEqual(len(active), 1)
            time.sleep(0.01)
            with lock:
                active[cell["model"]] -= 1
                if active[cell["model"]] == 0:
                    del active[cell["model"]]
            return {"run_id": run_id}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            matrix = root / "matrix.json"
            output = root / "rows.jsonl"
            matrix.write_text(
                json.dumps(
                    {
                        "n_per_cell": 4,
                        "grid": {"model": ["a", "b"], "concurrency": [2]},
                    }
                )
            )
            with patch("harness.runner.one_request", request):
                first = run(str(matrix), str(output), "http://unused")
                second = run(str(matrix), str(output), "http://unused")

        self.assertEqual(first["written"], 8)
        self.assertEqual(second["written"], 0)
        self.assertEqual(second["skipped_resume"], 8)
