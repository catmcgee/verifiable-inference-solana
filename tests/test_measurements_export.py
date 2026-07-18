from __future__ import annotations

import unittest

from report.measurements_json import _all_request_rows


class MeasurementsExportTests(unittest.TestCase):
    def test_export_contains_every_unique_schema_valid_request(self) -> None:
        rows, stored = _all_request_rows()
        ids = [row["run_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreater(stored, len(rows))
        self.assertTrue(any(row["model"] == "glm-5.2-q4" for row in rows))
        self.assertTrue(any(row["leg"] == "C-direct" for row in rows))
        self.assertTrue(any(row["leg"] == "C-proxied" for row in rows))


if __name__ == "__main__":
    unittest.main()
