"""Guest-side client for the hash-only Solana receipt relay."""

from __future__ import annotations

import os
from pathlib import Path

import httpx


def _token() -> str:
    value = os.environ.get("VINFER_RECEIPT_RELAY_TOKEN", "")
    path = os.environ.get("VINFER_RECEIPT_RELAY_TOKEN_FILE", "")
    if not value and path:
        value = Path(path).read_text().strip()
    return value


async def post_receipt(receipt: dict) -> dict | None:
    url = os.environ.get("VINFER_RECEIPT_RELAY_URL", "")
    if not url:
        return None
    token = _token()
    if len(token) < 32:
        raise RuntimeError("receipt relay is configured without a valid token")
    payload = {
        key: receipt[key]
        for key in (
            "receipt_id",
            "enclave_pubkey_b64",
            "prompt_hash",
            "response_hash",
            "model_hash",
            "timestamp",
            "sig_b64",
        )
    }
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{url.rstrip('/')}/v1/receipts/post",
            json=payload,
            headers={"authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()
