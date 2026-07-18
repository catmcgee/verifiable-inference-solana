import unittest

from server.receipts.store import ReceiptStore


class ReceiptStoreTests(unittest.TestCase):
    def test_evicts_oldest_receipt_at_capacity(self):
        store = ReceiptStore(max_entries=2)
        store["first"] = {"receipt_id": "first"}
        store["second"] = {"receipt_id": "second"}
        store["third"] = {"receipt_id": "third"}

        self.assertIsNone(store.get("first"))
        self.assertEqual(store.get("second"), {"receipt_id": "second"})
        self.assertEqual(len(store), 2)

    def test_rejects_non_positive_capacity(self):
        with self.assertRaises(ValueError):
            ReceiptStore(max_entries=0)


if __name__ == "__main__":
    unittest.main()
