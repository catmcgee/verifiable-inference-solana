"""verified-inference server.

Registry-driven (models.yaml is the single source of truth).
Canonical surfaces: POST /v1/chat/completions for TLS chat and POST
/v1/chat_e2e for attestation-gated sealed chat. Serves real models from
models.yaml.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
import httpx
from pydantic import BaseModel, Field, ValidationError

from server import access, openai, registry, runtimes
from server.attest.report import build_attestation
from server.execution import load_identity
from server.receipts.request_hash import canonical_request
from server.receipts.issue import issue_receipt
from server.receipts.signer import EnclaveSigner
from server.receipts.store import ReceiptStore
from server.request_validation import (
    ChatRequest,
    MAX_CIPHERTEXT_CHARS,
    MAX_OUTPUT_TOKENS,
)

BACKEND = "llama"
REGISTRY = registry.load()


def _registry_pairs() -> list[dict]:
    """Every hash-bearing models.yaml entry, per binding-v2."""
    return [
        {"id": m.id, "weights_sha256": m.weights_sha256}
        for m in REGISTRY.values()
        if m.servable
    ]


SERVER_BUILD = "vinfer-0.8.3"
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
            503, f"model {model_id!r} runtime is not currently available"
        )
    return entry


def model_weights_hash(model_id: str) -> bytes:
    return _servable(model_id).weights_hash


async def _chat(model_id: str, messages: list[dict], max_tokens: int) -> dict:
    return await runtimes.for_model(_servable(model_id)).chat(messages, max_tokens)


@asynccontextmanager
async def lifespan(app: FastAPI):
    access.validate_config()
    # Enclave keys: generated at boot, in-memory only, never persisted.
    app.state.signer = EnclaveSigner()
    from server.crypto.hpke_box import EnclaveHpkeKey

    app.state.hpke = EnclaveHpkeKey()
    app.state.receipts = ReceiptStore()
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

    async def refresh_available_models() -> None:
        while True:
            await asyncio.sleep(5)
            refreshed = await asyncio.gather(
                *(healthy(model_id) for model_id in sorted(candidates))
            )
            app.state.available_model_ids = frozenset(
                model_id for model_id, ok in refreshed if ok
            )

    refresh_task = asyncio.create_task(refresh_available_models())
    try:
        yield
    finally:
        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="verified-inference", version="0.8.3", lifespan=lifespan)
app.include_router(access.router)


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


class SealedChatRequest(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    enc: str = Field(min_length=1, max_length=256)  # HPKE encapsulated key (base64)
    ciphertext: str = Field(
        min_length=1, max_length=MAX_CIPHERTEXT_CHARS
    )  # HPKE-sealed prompt (base64)
    max_tokens: int = Field(default=256, ge=1, le=MAX_OUTPUT_TOKENS)
    stream: bool = False


@app.post("/v1/chat_e2e")
async def chat_e2e(req: SealedChatRequest, request: Request):
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
    if not isinstance(payload, dict) or payload.get("schema") != "vinfer-e2e-chat-v1":
        raise HTTPException(400, "sealed payload must contain a v1 chat")
    try:
        inner_request = ChatRequest(
            model=req.model,
            messages=payload.get("messages"),
            max_tokens=req.max_tokens,
            stream=req.stream,
        )
    except ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    messages = inner_request.messages
    request_preimage = canonical_request(
        endpoint="openai-chat-completions",
        model=req.model,
        messages=messages,
        max_tokens=req.max_tokens,
    )
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

    if req.stream:

        async def event_stream():
            result = None
            async for event in runtimes.for_model(_servable(req.model)).chat_stream(
                messages, req.max_tokens
            ):
                if event["type"] == "token":
                    yield openai.sse(
                        {"sealed_delta": sess.seal_response(event["text"].encode())}
                    )
                else:
                    result = event["result"]
            if result is None:
                raise RuntimeError("runtime stream ended without a result")
            yield openai.sse(await seal_result(result))
            yield openai.sse("[DONE]")

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers=openai.STREAM_HEADERS,
        )

    result = await _chat(req.model, messages, req.max_tokens)
    body = await seal_result(result)
    return openai.response_with_receipt(body, body["receipt"])


async def _sign(
    prompt: str | bytes,
    text: str,
    model_id: str,
    metrics: dict,
    receipts: ReceiptStore,
) -> dict:
    return await issue_receipt(
        signer=app.state.signer,
        prompt=prompt,
        text=text,
        model_hash=model_weights_hash(model_id),
        metrics=metrics,
        attestation=_attestation_doc,
        receipts=receipts,
    )


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
                    yield openai.sse(
                        openai.stream_chunk(
                            completion_id, req.model, content=event["text"]
                        )
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
            yield openai.sse(
                openai.stream_chunk(
                    completion_id,
                    req.model,
                    finish_reason=result.get("finish_reason", "stop"),
                    usage=result["usage"],
                    extension={
                        "metrics": result["metrics"],
                        "receipt": receipt,
                        "registry_hash": _registry_hash().hex(),
                        "attestation_grade": receipt["attestation"]["grade"],
                        "settlement": settlement,
                    },
                )
            )
            yield openai.sse("[DONE]")

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers=openai.STREAM_HEADERS,
        )
    result = await _chat(req.model, req.messages, req.max_tokens)
    settlement = {"metered": False, "access": access_mode}
    receipt = await _sign(
        prompt_repr, result["text"], req.model, result["metrics"], app.state.receipts
    )
    resp = openai.completion_body(
        f"chatcmpl-{uuid.uuid4().hex[:20]}",
        req.model,
        result["text"],
        result.get("finish_reason", "stop"),
        result["usage"],
        {
            "metrics": result["metrics"],
            "receipt": receipt,
            "registry_hash": _registry_hash().hex(),
            "attestation_grade": receipt["attestation"]["grade"],
            "settlement": settlement,
        },
    )
    return openai.response_with_receipt(resp, receipt)


@app.get("/v1/receipts/{receipt_id}", summary="Fetch a signed inference receipt")
async def get_receipt(receipt_id: str):
    receipt = app.state.receipts.get(receipt_id)
    if receipt is None:
        raise HTTPException(404, "unknown receipt")
    return receipt
