"""verified-inference server.

Backends: VINFER_BACKEND=mock (default, local dev) | llama (real llama-server
proxies on the box). Run: uv run uvicorn server.main:app --port 8477
"""

from __future__ import annotations

import hashlib
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from server import mock_backend
from server.attest.mock import build_attestation
from server.receipts.signer import EnclaveSigner

BACKEND = os.environ.get("VINFER_BACKEND", "mock")
if BACKEND == "llama":
    from server import llama_backend as backend

    MODELS = backend.REAL_MODELS
else:
    backend = mock_backend
    MODELS = mock_backend.MODELS

SERVER_BUILD = f"p2-{BACKEND}-0.2.0"
SERVER_BUILD_HASH = hashlib.sha256(SERVER_BUILD.encode()).digest()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Enclave key: generated at boot, in-memory only, never persisted (standing rule)
    app.state.signer = EnclaveSigner()
    app.state.receipts = {}
    yield


app = FastAPI(title="verified-inference", version="0.1.0", lifespan=lifespan)


class InferRequest(BaseModel):
    model: str
    prompt: str
    max_tokens: int = Field(default=64, ge=1, le=4096)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "build": SERVER_BUILD, "sev_mode": backend.SEV_MODE}


@app.get("/v1/models")
async def models():
    return {
        "models": [
            {"name": name, "quant": cfg["quant"], "backend": BACKEND,
             "weights_hash": backend.model_weights_hash(name).hex()}
            for name, cfg in MODELS.items()
        ]
    }


@app.get("/v1/attestation")
async def attestation():
    # One attestation binds the enclave key + ALL served model hashes via a
    # combined hash; per-model REPORT_DATA is a P3 decision once snpguest exists.
    combined = hashlib.sha256(
        b"".join(backend.model_weights_hash(m) for m in sorted(MODELS))
    ).digest()
    return build_attestation(app.state.signer.pubkey_b64, combined, SERVER_BUILD_HASH)


@app.post("/v1/infer")
async def infer(req: InferRequest):
    if req.model not in MODELS:
        raise HTTPException(404, f"unknown model {req.model!r}")
    result = await backend.generate(req.model, req.prompt, req.max_tokens)

    t0 = time.perf_counter()
    receipt = app.state.signer.sign_receipt(
        req.prompt, result["text"], backend.model_weights_hash(req.model)
    )
    result["metrics"]["receipt_sign_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)

    app.state.receipts[receipt["receipt_id"]] = receipt
    return {"model": req.model, **result, "receipt": receipt}


@app.get("/v1/receipts/{receipt_id}")
async def get_receipt(receipt_id: str):
    receipt = app.state.receipts.get(receipt_id)
    if receipt is None:
        raise HTTPException(404, "unknown receipt")
    return receipt
