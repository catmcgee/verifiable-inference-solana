"""Authenticated host-side relay for posting hash-only inference receipts."""

from __future__ import annotations

import hmac
import os
from functools import lru_cache

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from server.receipts.poster import ReceiptPostError, ReceiptPoster


class RelayReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(min_length=1, max_length=64)
    enclave_pubkey_b64: str = Field(min_length=40, max_length=48)
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    timestamp: int
    sig_b64: str = Field(min_length=84, max_length=92)


@lru_cache(maxsize=1)
def _token() -> str:
    token = os.environ.get("VINFER_RECEIPT_RELAY_TOKEN", "")
    token_file = os.environ.get("VINFER_RECEIPT_RELAY_TOKEN_FILE", "")
    if not token and token_file:
        token = open(token_file, encoding="utf-8").read().strip()
    if len(token) < 32:
        raise RuntimeError(
            "VINFER_RECEIPT_RELAY_TOKEN must contain at least 32 characters"
        )
    return token


@lru_cache(maxsize=1)
def _poster() -> ReceiptPoster:
    return ReceiptPoster(
        os.environ.get("VINFER_SOLANA_PAYER", "solana/.devnet-deployer.json"),
        os.environ.get("VINFER_SOLANA_RPC", "https://api.devnet.solana.com"),
    )


app = FastAPI(title="vinfer hash-only receipt relay", docs_url=None, redoc_url=None)


@app.get("/healthz")
def healthz() -> dict:
    _token()
    _poster()
    return {"ok": True, "network": "solana-devnet", "payload": "hashes-only"}


@app.post("/v1/receipts/post")
def post_receipt(
    receipt: RelayReceipt,
    authorization: str | None = Header(default=None),
) -> dict:
    expected = f"Bearer {_token()}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "invalid relay authorization")
    try:
        return _poster().post(receipt.model_dump())
    except ReceiptPostError as exc:
        raise HTTPException(422, str(exc)) from exc
