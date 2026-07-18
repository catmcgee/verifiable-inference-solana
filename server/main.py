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
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
from pydantic import BaseModel, Field

from server import access, registry, runtimes
from server.attest.report import build_attestation
from server.execution import load_identity
from server.receipts.request_hash import canonical_request
from server.receipts.signer import EnclaveSigner
from server.receipts.solana import attestation_pda

# REAL backend only. There is no mock — the server serves the actual models in
# models.yaml via their runtimes, or it errors. (This is a measurement/serving
# system; a mock would make every number and every attestation a lie.)
BACKEND = "llama"
REGISTRY = registry.load()


def _registry_pairs() -> list[dict]:
    """Every hash-bearing models.yaml entry, per binding-v2."""
    return [
        {"id": m.id, "weights_sha256": m.weights_sha256}
        for m in REGISTRY.values()
        if m.servable
    ]


SERVER_BUILD = "vinfer-0.8.0"
STATIC_REGISTRY_HASH = registry.pairs_hash(_registry_pairs())
BUILD_IDENTITY = load_identity(SERVER_BUILD, STATIC_REGISTRY_HASH)
SERVER_BUILD_HASH = BUILD_IDENTITY.build_hash


def _registry_hash() -> bytes:
    return app.state.registry_hash


def _attestation_doc() -> dict:
    hpke_public_key = app.state.hpke.public_key_b64
    document = build_attestation(
        app.state.signer.pubkey_b64,
        _registry_hash(),
        SERVER_BUILD_HASH,
        registry=app.state.registry_pairs,
        hpke_public_key_b64=hpke_public_key,
        hpke_binding_signature_b64=app.state.signer.sign_hpke_public_key(
            hpke_public_key
        ),
        execution=BUILD_IDENTITY.public_document(),
    )
    document["active_models"] = sorted(app.state.available_model_ids)
    document["runtime_version"] = SERVER_BUILD
    return document


def _servable(model_id: str) -> registry.ModelEntry:
    entry = REGISTRY.get(model_id)
    if entry is None:
        raise HTTPException(404, f"unknown model {model_id!r}")
    if not entry.servable:
        raise HTTPException(503, f"model {model_id!r} has no weights on this host")
    if model_id not in app.state.available_model_ids:
        raise HTTPException(
            503, f"model {model_id!r} runtime was unavailable at attestation"
        )
    return entry


def model_weights_hash(model_id: str) -> bytes:
    return _servable(model_id).weights_hash


def _canonical_raw_request(model: str, prompt: str, max_tokens: int) -> bytes:
    return canonical_request(
        endpoint="raw-prompt",
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )


async def _generate(model_id: str, prompt: str, max_tokens: int) -> dict:
    runtime = runtimes.for_model(_servable(model_id))
    result = await runtime.generate(prompt, max_tokens)
    if "usage" not in result:
        prompt_tokens = len(await runtime.tokenize(prompt))
        completion_tokens = result["metrics"].get("output_tokens")
        if type(completion_tokens) is not int or completion_tokens < 0:
            raise RuntimeError("runtime returned an invalid output token count")
        result["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    return result


async def _chat(model_id: str, messages: list[dict], max_tokens: int) -> dict:
    return await runtimes.for_model(_servable(model_id)).chat(messages, max_tokens)


def _sse(payload: dict | str) -> str:
    value = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, separators=(",", ":"))
    )
    return f"data: {value}\n\n"


@asynccontextmanager
async def lifespan(app: FastAPI):
    access.validate_config()
    # Enclave keys: generated at boot, in-memory only, never persisted.
    app.state.signer = EnclaveSigner()
    from server.crypto.hpke_box import EnclaveHpkeKey

    app.state.hpke = EnclaveHpkeKey()
    app.state.receipts = {}
    configured = os.environ.get("VINFER_AVAILABLE_MODELS", "")
    candidates = (
        {item.strip() for item in configured.split(",") if item.strip()}
        if configured
        else {m.id for m in REGISTRY.values() if m.servable}
    )
    unknown = candidates - set(REGISTRY)
    if unknown:
        raise RuntimeError(
            f"VINFER_AVAILABLE_MODELS contains unknown IDs: {sorted(unknown)}"
        )

    async def healthy(model_id: str) -> tuple[str, bool]:
        try:
            await runtimes.for_model(REGISTRY[model_id]).load()
            return model_id, True
        except (httpx.HTTPError, RuntimeError):
            return model_id, False

    probes = await asyncio.gather(
        *(healthy(model_id) for model_id in sorted(candidates))
    )
    app.state.available_model_ids = frozenset(model_id for model_id, ok in probes if ok)
    if not app.state.available_model_ids:
        raise RuntimeError(
            "no configured model runtime passed its startup health probe"
        )
    app.state.registry_pairs = _registry_pairs()
    app.state.registry_hash = registry.pairs_hash(app.state.registry_pairs)
    BUILD_IDENTITY.validate_registry(app.state.registry_hash)
    # Inside an SNP guest: request a real hardware report bound to THIS key +
    # registry + build (REPORT_DATA = the binding hash). Grade becomes "snp"
    # only if the hardware actually returns one — otherwise launch-only.
    from server.attest.report import ensure_snp_report
    import base64 as _b64

    binding = hashlib.sha256(
        _b64.b64decode(app.state.signer.pubkey_b64)
        + app.state.registry_hash
        + SERVER_BUILD_HASH
    ).digest()
    ensure_snp_report(binding)
    yield


app = FastAPI(title="verified-inference", version="0.8.0", lifespan=lifespan)


class InferRequest(BaseModel):
    model: str
    prompt: str
    max_tokens: int = Field(default=64, ge=1, le=4096)


class ChatRequest(BaseModel):
    model: str
    messages: list[dict]
    max_tokens: int = Field(default=256, ge=1, le=131072)
    stream: bool = False


class AuthSessionRequest(BaseModel):
    access_code: str = Field(min_length=1, max_length=512)


@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "build": SERVER_BUILD,
        "backend": BACKEND,
        "sev_mode": os.environ.get("VINFER_SEV_MODE", "off"),
        "registry_hash": _registry_hash().hex(),
        "available_models": sorted(app.state.available_model_ids),
    }


@app.get("/v1/models", summary="List available attested inference models")
async def models():
    return {
        "object": "list",
        "data": [
            {
                "id": m.id,
                "object": "model",
                "owned_by": "verified-inference",
                "quant": m.quant,
                "runtime": m.runtime,
                "legs": list(m.legs),
                "ctx_max": m.ctx_max,
                "backend": BACKEND,
                "status": (
                    "available"
                    if m.id in app.state.available_model_ids
                    else "runtime-unavailable"
                    if m.servable
                    else "no-weights-on-host"
                ),
                "weights_sha256": m.weights_sha256,
                "price_per_1m_in_usdc": m.price_per_1m_in_usdc,
                "price_per_1m_out_usdc": m.price_per_1m_out_usdc,
            }
            for m in REGISTRY.values()
        ],
    }


@app.get("/v1/attestation", summary="Fetch the current SNP attestation document")
async def attestation():
    # Binding v2: REPORT_DATA = sha256(enclave_pubkey || registry_hash || build_hash)
    return _attestation_doc()


@app.get("/v1/auth/session", summary="Check browser test-session status")
async def auth_session_status(request: Request):
    config = access.settings()
    mode = access.access_mode(request)
    return JSONResponse(
        content={
            "required": config.required,
            "authenticated": mode is not None,
            "mode": mode,
        },
        headers={"Cache-Control": "no-store, private"},
    )


@app.post("/v1/auth/session", summary="Create a browser test session")
async def auth_session_create(req: AuthSessionRequest):
    if not access.access_code_valid(req.access_code):
        return JSONResponse(
            status_code=401,
            content={"error": "invalid access code"},
            headers={"Cache-Control": "no-store, private"},
        )
    response = JSONResponse(
        content={"required": access.settings().required, "authenticated": True},
        headers={"Cache-Control": "no-store, private"},
    )
    access.set_session_cookie(response)
    return response


@app.delete("/v1/auth/session", summary="End a browser test session")
async def auth_session_delete():
    response = JSONResponse(
        content={"authenticated": False},
        headers={"Cache-Control": "no-store, private"},
    )
    access.clear_session_cookie(response)
    return response


class SealedInferRequest(BaseModel):
    model: str
    enc: str  # HPKE encapsulated key (base64)
    ciphertext: str  # HPKE-sealed prompt (base64)
    max_tokens: int = Field(default=64, ge=1, le=4096)
    stream: bool = False


@app.post("/v1/infer_sealed", summary="Run inference with an HPKE-sealed prompt")
async def infer_sealed(req: SealedInferRequest, request: Request):
    """input_mode=hpke: prompt arrives encrypted to the enclave HPKE key and is
    decrypted here (inside the enclave), never visible to a TLS-terminating proxy."""
    access_mode, err = access.require(request)
    if err is not None:
        return err
    t0 = time.perf_counter()
    try:
        prompt = app.state.hpke.open(req.enc, req.ciphertext).decode()
    except Exception:
        raise HTTPException(
            400, "HPKE decrypt failed (wrong key or tampered ciphertext)"
        )
    decrypt_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    _servable(req.model)
    result = await _generate(req.model, prompt, req.max_tokens)
    result["metrics"]["hpke_decrypt_ms"] = decrypt_ms
    result["metrics"]["e2e_ms"] = round(result["metrics"]["e2e_ms"] + decrypt_ms, 3)
    result["metrics"]["input_mode"] = "hpke"
    settlement = {"metered": False, "access": access_mode}
    receipt = await _sign(
        _canonical_raw_request(req.model, prompt, req.max_tokens),
        result["text"],
        req.model,
        result["metrics"],
        app.state.receipts,
    )
    return _completion_response(
        {"model": req.model, **result, "receipt": receipt, "settlement": settlement},
        receipt,
        settlement,
    )


@app.post("/v1/chat_e2e")
async def chat_e2e(req: SealedInferRequest, request: Request):
    """Attestation-gated end-to-end sealed session: prompt AND response are
    encrypted under an HPKE-exporter session key bound to the enclave key the
    client verified from the attestation. The operator sees ciphertext both ways.
    Prompt text never leaves the sealed request. Response text, metrics, and
    usage are sealed separately; the outer response carries only ciphertext,
    routing metadata, and the hash-only receipt."""
    from server.crypto.session_box import ServerSession

    access_mode, err = access.require(request)
    if err is not None:
        return err
    t0 = time.perf_counter()
    try:
        sess = ServerSession(app.state.hpke, req.enc)
        plaintext = sess.open_prompt(req.ciphertext).decode()
    except Exception:
        raise HTTPException(
            400, "session open failed (wrong key or tampered ciphertext)"
        )
    open_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    _servable(req.model)
    try:
        payload = json.loads(plaintext)
    except json.JSONDecodeError:
        payload = None
    messages = None
    if (
        isinstance(payload, dict)
        and payload.get("schema") == "vinfer-e2e-chat-v1"
        and isinstance(payload.get("messages"), list)
    ):
        messages = payload["messages"]
        request_preimage = canonical_request(
            endpoint="openai-chat-completions",
            model=req.model,
            messages=messages,
            max_tokens=req.max_tokens,
        )
    else:
        request_preimage = _canonical_raw_request(req.model, plaintext, req.max_tokens)
    settlement = {"metered": False, "access": access_mode}

    async def seal_result(result: dict) -> dict:
        result["metrics"]["session_open_ms"] = open_ms
        result["metrics"]["input_mode"] = "e2e-sealed"
        receipt = await _sign(
            request_preimage,
            result["text"],
            req.model,
            result["metrics"],
            app.state.receipts,
        )
        sealed = sess.seal_response(result["text"].encode())
        sealed_meta = sess.seal_response(
            json.dumps(result["metrics"], separators=(",", ":")).encode()
        )
        sealed_usage = sess.seal_response(
            json.dumps(result["usage"], separators=(",", ":")).encode()
        )
        return {
            "model": req.model,
            **sealed,
            "sealed_metrics": sealed_meta,
            "sealed_usage": sealed_usage,
            "receipt": receipt,
            "settlement": settlement,
        }

    if req.stream and messages is not None:

        async def event_stream():
            result = None
            async for event in runtimes.for_model(_servable(req.model)).chat_stream(
                messages, req.max_tokens
            ):
                if event["type"] == "token":
                    yield _sse(
                        {"sealed_delta": sess.seal_response(event["text"].encode())}
                    )
                else:
                    result = event["result"]
            if result is None:
                raise RuntimeError("runtime stream ended without a result")
            yield _sse(await seal_result(result))
            yield _sse("[DONE]")

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, no-transform, private",
                "X-Accel-Buffering": "no",
            },
        )

    result = (
        await _chat(req.model, messages, req.max_tokens)
        if messages is not None
        else await _generate(req.model, plaintext, req.max_tokens)
    )
    body = await seal_result(result)
    return _completion_response(
        body,
        body["receipt"],
        settlement,
    )


async def _sign(
    prompt: str | bytes,
    text: str,
    model_id: str,
    metrics: dict,
    receipts: dict,
) -> dict:
    t0 = time.perf_counter()
    try:
        receipt = app.state.signer.sign_receipt(
            prompt, text, model_weights_hash(model_id)
        )
    finally:
        metrics["receipt_sign_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
    # Embed the attestation doc the receipt was issued under, so the receipt is
    # self-verifiable offline (`vinfer verify` checks it, then cross-anchors it
    # against the on-chain PDA). No HPKE extras — just the binding fields.
    receipt["attestation"] = _attestation_doc()
    receipt["attestation_pda"] = attestation_pda(receipt["enclave_pubkey_b64"])
    receipt["onchain_status"] = "not-posted"
    metrics.setdefault("receipt_post_ms", 0)
    metrics.setdefault("receipt_confirm_ms", 0)
    metrics.setdefault("solana_cu", 0)
    metrics.setdefault("solana_fee_lamports", 0)
    try:
        from server.receipts.relay_client import post_receipt

        posted = await post_receipt(receipt)
        if posted:
            receipt.update(
                {
                    key: posted[key]
                    for key in (
                        "onchain_status",
                        "receipt_index",
                        "receipt_pda",
                        "receipt_tx",
                    )
                }
            )
            for key in (
                "receipt_post_ms",
                "receipt_confirm_ms",
                "solana_cu",
                "solana_fee_lamports",
            ):
                metrics[key] = posted[key]
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger("vinfer").warning(
            "receipt relay failed for receipt_id=%s (%s)",
            receipt["receipt_id"],
            type(exc).__name__,
        )
    receipts[receipt["receipt_id"]] = receipt
    return receipt


@app.post("/v1/chat/completions", summary="Generate an attested chat completion")
async def chat_completions(req: ChatRequest, request: Request):
    _servable(req.model)
    prompt_repr = canonical_request(
        endpoint="openai-chat-completions",
        model=req.model,
        messages=req.messages,
        max_tokens=req.max_tokens,
    )
    access_mode, err = access.require(request)
    if err is not None:
        return err
    if req.stream:
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:20]}"

        async def event_stream():
            result = None
            async for event in runtimes.for_model(_servable(req.model)).chat_stream(
                req.messages, req.max_tokens
            ):
                if event["type"] == "token":
                    yield _sse(
                        {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": req.model,
                            "choices": [
                                {
                                    "index": 0,
                                    "finish_reason": None,
                                    "delta": {"content": event["text"]},
                                }
                            ],
                        }
                    )
                else:
                    result = event["result"]
            if result is None:
                raise RuntimeError("runtime stream ended without a result")
            settlement = {"metered": False, "access": access_mode}
            receipt = await _sign(
                prompt_repr,
                result["text"],
                req.model,
                result["metrics"],
                app.state.receipts,
            )
            yield _sse(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": req.model,
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": result.get("finish_reason", "stop"),
                            "delta": {},
                        }
                    ],
                    "usage": result["usage"],
                    "x_vinfer": {
                        "metrics": result["metrics"],
                        "receipt": receipt,
                        "registry_hash": _registry_hash().hex(),
                        "attestation_grade": receipt["attestation"]["grade"],
                        "settlement": settlement,
                    },
                }
            )
            yield _sse("[DONE]")

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, no-transform, private",
                "X-Accel-Buffering": "no",
            },
        )
    result = await _chat(req.model, req.messages, req.max_tokens)
    settlement = {"metered": False, "access": access_mode}
    receipt = await _sign(
        prompt_repr, result["text"], req.model, result["metrics"], app.state.receipts
    )
    resp = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:20]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices": [
            {
                "index": 0,
                "finish_reason": result.get("finish_reason", "stop"),
                "message": {"role": "assistant", "content": result["text"]},
            }
        ],
        "usage": result["usage"],
        "x_vinfer": {
            "metrics": result["metrics"],
            "receipt": receipt,
            "registry_hash": _registry_hash().hex(),
            "attestation_grade": receipt["attestation"]["grade"],
            "settlement": settlement,
        },
    }
    return _completion_response(resp, receipt, settlement)


@app.post("/v1/infer")
async def infer(req: InferRequest, request: Request):
    """Raw-prompt alias of the canonical surface (harness/bench path)."""
    _servable(req.model)
    access_mode, err = access.require(request)
    if err is not None:
        return err
    result = await _generate(req.model, req.prompt, req.max_tokens)
    settlement = {"metered": False, "access": access_mode}
    receipt = await _sign(
        _canonical_raw_request(req.model, req.prompt, req.max_tokens),
        result["text"],
        req.model,
        result["metrics"],
        app.state.receipts,
    )
    return _completion_response(
        {"model": req.model, **result, "receipt": receipt, "settlement": settlement},
        receipt,
        settlement,
    )


def _completion_response(body: dict, receipt: dict, settlement: dict) -> JSONResponse:
    headers = {"X-Vinfer-Receipt-Id": receipt["receipt_id"]}
    return JSONResponse(content=body, headers=headers)


@app.get("/v1/receipts/{receipt_id}", summary="Fetch a signed inference receipt")
async def get_receipt(receipt_id: str):
    receipt = app.state.receipts.get(receipt_id)
    if receipt is None:
        raise HTTPException(404, "unknown receipt")
    return receipt
