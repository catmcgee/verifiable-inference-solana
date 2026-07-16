"""verified-inference server.

Registry-driven (models.yaml is the single source of truth — ADDON step 1/2).
Canonical surface: POST /v1/chat/completions · GET /v1/models · GET
/v1/attestation · GET /v1/receipts/{id}. POST /v1/infer is a thin raw-prompt
alias used by the harness. Backends: VINFER_BACKEND=mock (default) | llama.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from server import mock_backend, registry, runtimes
from server.attest.mock import build_attestation
from server.receipts.signer import EnclaveSigner

BACKEND = os.environ.get("VINFER_BACKEND", "mock")
REGISTRY = registry.load()


def _attested_pairs() -> list[dict]:
    """What this process ACTUALLY serves. Mock serves mock weights, so it
    attests mock hashes — attestation never claims weights that aren't there."""
    if BACKEND == "mock":
        return [{"id": m.id, "weights_sha256": mock_backend.model_weights_hash(m.id).hex()}
                for m in REGISTRY.values()]
    return [{"id": m.id, "weights_sha256": m.weights_sha256}
            for m in REGISTRY.values() if m.servable]


REGISTRY_HASH = registry.pairs_hash(_attested_pairs())
SERVER_BUILD = f"p2-{BACKEND}-0.3.0"
SERVER_BUILD_HASH = hashlib.sha256(SERVER_BUILD.encode()).digest()


def _servable(model_id: str) -> registry.ModelEntry:
    entry = REGISTRY.get(model_id)
    if entry is None:
        raise HTTPException(404, f"unknown model {model_id!r}")
    if not entry.servable:
        raise HTTPException(503, f"model {model_id!r} is pending (weights not on box yet)")
    return entry


def model_weights_hash(model_id: str) -> bytes:
    if BACKEND == "mock":
        return mock_backend.model_weights_hash(model_id)
    return _servable(model_id).weights_hash


async def _generate(model_id: str, prompt: str, max_tokens: int) -> dict:
    if BACKEND == "mock":
        return await mock_backend.generate(model_id, prompt, max_tokens)
    return await runtimes.for_model(_servable(model_id)).generate(prompt, max_tokens)


async def _chat(model_id: str, messages: list[dict], max_tokens: int) -> dict:
    if BACKEND == "mock":
        prompt = "\n".join(m.get("content", "") for m in messages)
        return await mock_backend.generate(model_id, prompt, max_tokens)
    return await runtimes.for_model(_servable(model_id)).chat(messages, max_tokens)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Enclave keys: generated at boot, in-memory only, never persisted.
    app.state.signer = EnclaveSigner()
    from server.crypto.hpke_box import EnclaveHpkeKey

    app.state.hpke = EnclaveHpkeKey()
    app.state.receipts = {}
    yield


app = FastAPI(title="verified-inference", version="0.3.0", lifespan=lifespan)


class InferRequest(BaseModel):
    model: str
    prompt: str
    max_tokens: int = Field(default=64, ge=1, le=4096)


class ChatRequest(BaseModel):
    model: str
    messages: list[dict]
    max_tokens: int = Field(default=256, ge=1, le=131072)
    stream: bool = False  # v1: non-stream responses (streaming lands with x402 gating)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "build": SERVER_BUILD, "backend": BACKEND,
            "sev_mode": os.environ.get("VINFER_SEV_MODE", "off"),
            "registry_hash": REGISTRY_HASH.hex()}


@app.get("/v1/models")
async def models():
    return {
        "object": "list",
        "data": [
            {
                "id": m.id, "object": "model", "owned_by": "verified-inference",
                "quant": m.quant, "runtime": m.runtime, "legs": list(m.legs),
                "ctx_max": m.ctx_max, "backend": BACKEND,
                "status": "available" if (m.servable or BACKEND == "mock") else "pending-weights",
                "weights_sha256": m.weights_sha256,
                "price_per_1m_in_usdc": m.price_per_1m_in_usdc,
                "price_per_1m_out_usdc": m.price_per_1m_out_usdc,
            }
            for m in REGISTRY.values()
        ],
    }


@app.get("/v1/attestation")
async def attestation():
    # Binding v2: REPORT_DATA = sha256(enclave_pubkey || registry_hash || build_hash)
    doc = build_attestation(
        app.state.signer.pubkey_b64, REGISTRY_HASH, SERVER_BUILD_HASH,
        registry=_attested_pairs(),
    )
    # HPKE public key for input_mode=hpke (encrypt-to-enclave). In the SNP case
    # this is bound to the attested ed25519 key; here it just rides the doc.
    doc["hpke_public_key_b64"] = app.state.hpke.public_key_b64
    doc["hpke_suite"] = "DHKEM(X25519,HKDF-SHA256)+HKDF-SHA256+ChaCha20Poly1305"
    return doc


class SealedInferRequest(BaseModel):
    model: str
    enc: str          # HPKE encapsulated key (base64)
    ciphertext: str   # HPKE-sealed prompt (base64)
    max_tokens: int = Field(default=64, ge=1, le=4096)


@app.post("/v1/infer_sealed")
async def infer_sealed(req: SealedInferRequest):
    """input_mode=hpke: prompt arrives encrypted to the enclave HPKE key and is
    decrypted here (inside the enclave), never visible to a TLS-terminating proxy."""
    t0 = time.perf_counter()
    try:
        prompt = app.state.hpke.open(req.enc, req.ciphertext).decode()
    except Exception:
        raise HTTPException(400, "HPKE decrypt failed (wrong key or tampered ciphertext)")
    decrypt_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    result = await _generate(req.model, prompt, req.max_tokens)
    result["metrics"]["hpke_decrypt_ms"] = decrypt_ms
    result["metrics"]["input_mode"] = "hpke"
    receipt = _sign(prompt, result["text"], req.model, result["metrics"], app.state.receipts)
    return {"model": req.model, **result, "receipt": receipt}


def _sign(prompt: str, text: str, model_id: str, metrics: dict, receipts: dict) -> dict:
    t0 = time.perf_counter()
    try:
        receipt = app.state.signer.sign_receipt(prompt, text, model_weights_hash(model_id))
    finally:
        metrics["receipt_sign_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
    receipts[receipt["receipt_id"]] = receipt
    return receipt


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest):
    if req.stream:
        raise HTTPException(400, "stream=true not yet supported; poll non-stream")
    result = await _chat(req.model, req.messages, req.max_tokens)
    prompt_repr = "\n".join(m.get("content", "") for m in req.messages)
    receipt = _sign(prompt_repr, result["text"], req.model, result["metrics"], app.state.receipts)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:20]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": result["text"]}}],
        "usage": result.get("usage") or {
            "prompt_tokens": 0, "completion_tokens": result["metrics"]["output_tokens"],
            "total_tokens": result["metrics"]["output_tokens"]},
        "x_vinfer": {"metrics": result["metrics"], "receipt": receipt,
                     "registry_hash": REGISTRY_HASH.hex()},
    }


@app.post("/v1/infer")
async def infer(req: InferRequest):
    """Raw-prompt alias of the canonical surface (harness/bench path)."""
    result = await _generate(req.model, req.prompt, req.max_tokens)
    receipt = _sign(req.prompt, result["text"], req.model, result["metrics"], app.state.receipts)
    return {"model": req.model, **result, "receipt": receipt}


@app.get("/v1/receipts/{receipt_id}")
async def get_receipt(receipt_id: str):
    receipt = app.state.receipts.get(receipt_id)
    if receipt is None:
        raise HTTPException(404, "unknown receipt")
    return receipt
