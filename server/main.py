"""verified-inference server.

Registry-driven (models.yaml is the single source of truth — ADDON step 1/2).
Canonical surface: POST /v1/chat/completions · GET /v1/models · GET
/v1/attestation · GET /v1/receipts/{id}. POST /v1/infer is a thin raw-prompt
alias used by the harness. Serves real models from models.yaml (no mock).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from server import registry, runtimes
from server.attest.report import build_attestation
from server.receipts.signer import EnclaveSigner
from server.x402 import middleware as x402

# REAL backend only. There is no mock — the server serves the actual models in
# models.yaml via their runtimes, or it errors. (This is a measurement/serving
# system; a mock would make every number and every attestation a lie.)
BACKEND = "llama"
REGISTRY = registry.load()


def _attested_pairs() -> list[dict]:
    """The models this process ACTUALLY serves (real weights only)."""
    return [{"id": m.id, "weights_sha256": m.weights_sha256}
            for m in REGISTRY.values() if m.servable]


REGISTRY_HASH = registry.pairs_hash(_attested_pairs())
SERVER_BUILD = "vinfer-0.4.0"
SERVER_BUILD_HASH = hashlib.sha256(SERVER_BUILD.encode()).digest()


def _servable(model_id: str) -> registry.ModelEntry:
    entry = REGISTRY.get(model_id)
    if entry is None:
        raise HTTPException(404, f"unknown model {model_id!r}")
    if not entry.servable:
        raise HTTPException(503, f"model {model_id!r} has no weights on this host")
    return entry


def model_weights_hash(model_id: str) -> bytes:
    return _servable(model_id).weights_hash


async def _generate(model_id: str, prompt: str, max_tokens: int) -> dict:
    return await runtimes.for_model(_servable(model_id)).generate(prompt, max_tokens)


async def _chat(model_id: str, messages: list[dict], max_tokens: int) -> dict:
    return await runtimes.for_model(_servable(model_id)).chat(messages, max_tokens)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Enclave keys: generated at boot, in-memory only, never persisted.
    app.state.signer = EnclaveSigner()
    from server.crypto.hpke_box import EnclaveHpkeKey

    app.state.hpke = EnclaveHpkeKey()
    app.state.receipts = {}
    # Inside an SNP guest: request a real hardware report bound to THIS key +
    # registry + build (REPORT_DATA = the binding hash). Grade becomes "snp"
    # only if the hardware actually returns one — otherwise launch-only.
    from server.attest.report import ensure_snp_report
    import base64 as _b64

    binding = hashlib.sha256(
        _b64.b64decode(app.state.signer.pubkey_b64) + REGISTRY_HASH + SERVER_BUILD_HASH
    ).digest()
    ensure_snp_report(binding)
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
                "status": "available" if m.servable else "no-weights-on-host",
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


@app.post("/v1/chat_e2e")
async def chat_e2e(req: SealedInferRequest):
    """Attestation-gated end-to-end sealed session: prompt AND response are
    encrypted under an HPKE-exporter session key bound to the enclave key the
    client verified from the attestation. The operator sees ciphertext both ways.
    Response body carries only {resp_nonce, sealed_response, receipt}."""
    from server.crypto.session_box import ServerSession

    t0 = time.perf_counter()
    try:
        sess = ServerSession(app.state.hpke, req.enc)
        prompt = sess.open_prompt(req.ciphertext).decode()
    except Exception:
        raise HTTPException(400, "session open failed (wrong key or tampered ciphertext)")
    open_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    result = await _generate(req.model, prompt, req.max_tokens)
    result["metrics"]["session_open_ms"] = open_ms
    result["metrics"]["input_mode"] = "e2e-sealed"
    # receipt still binds plaintext hashes (computed inside the enclave)
    receipt = _sign(prompt, result["text"], req.model, result["metrics"], app.state.receipts)
    sealed = sess.seal_response(result["text"].encode())
    # metrics ride sealed too (they'd otherwise leak output length); seal them
    import json as _json
    sealed_meta = sess.seal_response(_json.dumps(result["metrics"]).encode())
    return {"model": req.model, **sealed,
            "sealed_metrics": {"resp_nonce": sealed_meta["resp_nonce"],
                               "sealed_response": sealed_meta["sealed_response"]},
            "receipt": receipt}


def _sign(prompt: str, text: str, model_id: str, metrics: dict, receipts: dict) -> dict:
    t0 = time.perf_counter()
    try:
        receipt = app.state.signer.sign_receipt(prompt, text, model_weights_hash(model_id))
    finally:
        metrics["receipt_sign_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
    # Embed the attestation doc the receipt was issued under, so the receipt is
    # self-verifiable offline (`vinfer verify` checks it, then cross-anchors it
    # against the on-chain PDA). No HPKE extras — just the binding fields.
    receipt["attestation"] = build_attestation(
        app.state.signer.pubkey_b64, REGISTRY_HASH, SERVER_BUILD_HASH,
        registry=_attested_pairs(),
    )
    receipts[receipt["receipt_id"]] = receipt
    return receipt


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, request: Request):
    if req.stream:
        raise HTTPException(400, "stream=true not yet supported; poll non-stream")
    prompt_repr = "\n".join(m.get("content", "") for m in req.messages)
    # x402 session gate (no-op unless VINFER_X402=1); free endpoints stay free
    allowed, err, meter = await x402.gate(
        request, req.model, prompt_tokens=len(prompt_repr) // 4,
        max_tokens=req.max_tokens, registry=REGISTRY)
    if not allowed:
        return err
    result = await _chat(req.model, req.messages, req.max_tokens)
    settlement = x402.finalize(meter, result["metrics"]["output_tokens"], req.model, REGISTRY)
    receipt = _sign(prompt_repr, result["text"], req.model, result["metrics"], app.state.receipts)
    resp = {
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
                     "registry_hash": REGISTRY_HASH.hex(), "settlement": settlement},
    }
    headers = {"X-Vinfer-Receipt-Id": receipt["receipt_id"]}
    if settlement.get("metered"):
        headers["Payment-Receipt"] = json.dumps({
            "status": "success", "reference": settlement["channelId"],
            "spent": settlement["spent_total_micro_usdc"],
            "charged": settlement["charged_micro_usdc"]})
    return JSONResponse(content=resp, headers=headers)


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
