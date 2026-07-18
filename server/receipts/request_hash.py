"""Canonical, versioned request preimages for inference receipts."""

from __future__ import annotations

import json


REQUEST_HASH_VERSION = 2


def canonical_request(
    *, endpoint: str, model: str, messages: list[dict], max_tokens: int
) -> bytes:
    payload = {
        "endpoint": endpoint,
        "max_tokens": max_tokens,
        "messages": messages,
        "model": model,
        "schema": f"vinfer-request-v{REQUEST_HASH_VERSION}",
    }
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
