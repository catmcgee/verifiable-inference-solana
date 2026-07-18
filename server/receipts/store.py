"""Bounded in-memory lookup for recently issued receipts."""

from __future__ import annotations

import os
from collections import OrderedDict


DEFAULT_MAX_RECEIPTS = 10_000


class ReceiptStore:
    def __init__(self, max_entries: int | None = None):
        configured = (
            max_entries
            if max_entries is not None
            else int(os.environ.get("VINFER_RECEIPT_CACHE_SIZE", DEFAULT_MAX_RECEIPTS))
        )
        if configured <= 0:
            raise ValueError("receipt cache size must be positive")
        self.max_entries = configured
        self._items: OrderedDict[str, dict] = OrderedDict()

    def __setitem__(self, receipt_id: str, receipt: dict) -> None:
        self._items[receipt_id] = receipt
        self._items.move_to_end(receipt_id)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def get(self, receipt_id: str) -> dict | None:
        return self._items.get(receipt_id)

    def __len__(self) -> int:
        return len(self._items)
