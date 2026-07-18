import unittest

from harness.migrate_quant import migrate_rows


class QuantMigrationTests(unittest.TestCase):
    def test_fills_only_empty_quant(self):
        rows = [
            {"model": "small", "quant": ""},
            {"model": "small", "quant": "existing"},
            {"session_id": "not-a-request"},
        ]
        self.assertEqual(migrate_rows(rows, {"small": "Q4"}), 1)
        self.assertEqual(rows[0]["quant"], "Q4")
        self.assertEqual(rows[1]["quant"], "existing")

    def test_unknown_model_fails_closed(self):
        with self.assertRaises(ValueError):
            migrate_rows([{"model": "missing", "quant": ""}], {})


if __name__ == "__main__":
    unittest.main()
