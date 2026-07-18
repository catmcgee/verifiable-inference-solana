"""No-log OpenAI-compatible Anthropic proxy for live Leg C.

The SNP report attests the proxy VM identity and its declared build/registry
binding. It does not attest Anthropic's inference. Anthropic receives plaintext.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import statistics
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from server import access, registry
from server.attest.report import build_attestation, ensure_snp_report
from server.execution import load_identity
from server.receipts.relay_client import post_receipt
from server.receipts.request_hash import canonical_request
from server.receipts.signer import EnclaveSigner
from server.receipts.solana import attestation_pda


UPSTREAM = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = os.environ.get("VINFER_C_MODEL", "claude-haiku-4-5-20251001")
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PROXY_BUILD = "vinfer-legc-proxy-0.2.0"
MODEL_DECLARATION_HASH = hashlib.sha256(
    f"anthropic-upstream-model-id:{CLAUDE_MODEL}".encode()
).hexdigest()
REGISTRY = [
    {
        "id": CLAUDE_MODEL,
        "weights_sha256": MODEL_DECLARATION_HASH,
        "hash_semantics": "provider model ID declaration only; not model weights",
    }
]
REGISTRY_HASH = registry.pairs_hash(REGISTRY)
BUILD_IDENTITY = load_identity(PROXY_BUILD, REGISTRY_HASH)
PROXY_BUILD_HASH = BUILD_IDENTITY.build_hash


class ChatRequest(BaseModel):
    model: str
    messages: list[dict]
    max_tokens: int = Field(default=256, ge=1, le=8192)
    stream: bool = False


class AuthSessionRequest(BaseModel):
    access_code: str = Field(min_length=1, max_length=512)


def _sse(payload: dict | str) -> str:
    value = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, separators=(",", ":"))
    )
    return f"data: {value}\n\n"


def _attestation_doc(app: FastAPI) -> dict:
    document = dict(app.state.attestation)
    document.update(
        {
            "runtime_version": PROXY_BUILD,
            "active_models": [CLAUDE_MODEL],
            "component": "claude-attested-proxy",
            "upstream": "Anthropic",
            "provider_sees_plaintext": True,
            "inference_verifiable": False,
        }
    )
    document["note"] = (
        f"{document['note']} Leg C attests this proxy VM only. Anthropic receives "
        "plaintext and the upstream inference is not verifiable."
    )
    return document


@asynccontextmanager
async def lifespan(app: FastAPI):
    access.validate_config()
    if not API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is required")
    app.state.signer = EnclaveSigner()
    app.state.receipts = {}
    BUILD_IDENTITY.validate_registry(REGISTRY_HASH)
    binding = hashlib.sha256(
        base64.b64decode(app.state.signer.pubkey_b64) + REGISTRY_HASH + PROXY_BUILD_HASH
    ).digest()
    ensure_snp_report(binding)
    app.state.attestation = build_attestation(
        app.state.signer.pubkey_b64,
        REGISTRY_HASH,
        PROXY_BUILD_HASH,
        registry=REGISTRY,
        execution=BUILD_IDENTITY.public_document(),
    )
    yield


app = FastAPI(
    title="vinfer-leg-c-proxy",
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "ok": True,
        "build": PROXY_BUILD,
        "mode": "snp-egress-proxy",
        "sev_mode": os.environ.get("VINFER_SEV_MODE", "off"),
        "model": CLAUDE_MODEL,
    }


@app.get("/v1/models")
async def models() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": CLAUDE_MODEL,
                "object": "model",
                "owned_by": "anthropic-via-verified-inference",
                "quant": "provider-api",
                "runtime": "anthropic-proxy",
                "legs": ["C"],
                "ctx_max": 200000,
                "backend": "anthropic-via-snp-proxy",
                "status": "available",
                "weights_sha256": None,
                "price_per_1m_in_usdc": None,
                "price_per_1m_out_usdc": None,
            }
        ],
    }


@app.get("/v1/attestation")
async def attestation() -> dict:
    return _attestation_doc(app)


@app.get("/v1/auth/session")
async def auth_session_status(request: Request):
    config = access.settings()
    mode = access.access_mode(request)
    return JSONResponse(
        {"required": config.required, "authenticated": mode is not None, "mode": mode},
        headers={"Cache-Control": "no-store, private"},
    )


@app.post("/v1/auth/session")
async def auth_session_create(req: AuthSessionRequest):
    if not access.access_code_valid(req.access_code):
        return JSONResponse(
            status_code=401,
            content={"error": "invalid access code"},
            headers={"Cache-Control": "no-store, private"},
        )
    response = JSONResponse(
        {"required": access.settings().required, "authenticated": True},
        headers={"Cache-Control": "no-store, private"},
    )
    access.set_session_cookie(response)
    return response


@app.delete("/v1/auth/session")
async def auth_session_delete():
    response = JSONResponse(
        {"authenticated": False},
        headers={"Cache-Control": "no-store, private"},
    )
    access.clear_session_cookie(response)
    return response


async def _upstream_events(req: ChatRequest):
    client = httpx.AsyncClient(timeout=180)
    context = client.stream(
        "POST",
        UPSTREAM,
        headers={
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "accept-encoding": "identity",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": req.max_tokens,
            "stream": True,
            "messages": req.messages,
        },
    )
    upstream = await context.__aenter__()
    if upstream.is_error:
        status = upstream.status_code
        await upstream.aread()
        await context.__aexit__(None, None, None)
        await client.aclose()
        raise HTTPException(status, "Anthropic rejected the proxied request")
    return client, context, upstream


def _metrics(start: float, times: list[float], usage: dict) -> dict:
    end = time.perf_counter()
    if not times:
        raise RuntimeError("Anthropic stream returned no visible content")
    itls = [(times[index] - times[index - 1]) * 1000 for index in range(1, len(times))]
    output_tokens = int(usage.get("output_tokens", len(times)))
    duration = max(times[-1] - times[0], 0)
    ordered = sorted(itls) or [0.0]
    return {
        "ttft_ms": round((times[0] - start) * 1000, 3),
        "itl_ms_p50": round(statistics.median(ordered), 3),
        "itl_ms_p99": round(
            ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))], 3
        ),
        "tokens_per_s": round(max(0, output_tokens - 1) / duration, 3)
        if duration
        else 0.0,
        "e2e_ms": round((end - start) * 1000, 3),
        "output_tokens": output_tokens,
        "sev_mode": os.environ.get("VINFER_SEV_MODE", "off"),
        "backend": "anthropic-via-snp-proxy",
        "input_mode": "tls",
        "provider_sees_plaintext": True,
        "inference_verifiable": False,
    }


async def _receipt(prompt: bytes, text: str, metrics: dict) -> dict:
    start = time.perf_counter()
    receipt = app.state.signer.sign_receipt(
        prompt, text, bytes.fromhex(MODEL_DECLARATION_HASH)
    )
    metrics["receipt_sign_ms"] = round((time.perf_counter() - start) * 1000, 3)
    receipt["attestation"] = _attestation_doc(app)
    receipt["attestation_pda"] = attestation_pda(receipt["enclave_pubkey_b64"])
    receipt["onchain_status"] = "not-posted"
    for key in (
        "receipt_post_ms",
        "receipt_confirm_ms",
        "solana_cu",
        "solana_fee_lamports",
    ):
        metrics[key] = 0
    try:
        posted = await post_receipt(receipt)
        if posted:
            for key in ("onchain_status", "receipt_index", "receipt_pda", "receipt_tx"):
                receipt[key] = posted[key]
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
            "leg C receipt relay failed for receipt_id=%s (%s)",
            receipt["receipt_id"],
            type(exc).__name__,
        )
    app.state.receipts[receipt["receipt_id"]] = receipt
    return receipt


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, request: Request):
    if req.model != CLAUDE_MODEL:
        raise HTTPException(404, f"unknown model {req.model!r}")
    access_mode, error = access.require(request)
    if error is not None:
        return error
    prompt = canonical_request(
        endpoint="openai-chat-completions",
        model=req.model,
        messages=req.messages,
        max_tokens=req.max_tokens,
    )
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:20]}"

    async def generate():
        start = time.perf_counter()
        parts: list[str] = []
        times: list[float] = []
        usage: dict = {}
        client, context, upstream = await _upstream_events(req)
        try:
            async for line in upstream.aiter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event.get("type") == "error":
                    raise RuntimeError("Anthropic stream returned an error")
                if event.get("type") == "message_start":
                    usage.update(event.get("message", {}).get("usage", {}))
                elif event.get("type") == "message_delta":
                    usage.update(event.get("usage", {}))
                elif event.get("type") == "content_block_delta":
                    text = event.get("delta", {}).get("text", "")
                    if text:
                        parts.append(text)
                        times.append(time.perf_counter())
                        if req.stream:
                            yield _sse(
                                {
                                    "id": completion_id,
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": CLAUDE_MODEL,
                                    "choices": [
                                        {
                                            "index": 0,
                                            "finish_reason": None,
                                            "delta": {"content": text},
                                        }
                                    ],
                                }
                            )
        finally:
            await context.__aexit__(None, None, None)
            await client.aclose()
        text = "".join(parts)
        metrics = _metrics(start, times, usage)
        receipt = await _receipt(prompt, text, metrics)
        usage_out = {
            "prompt_tokens": int(usage.get("input_tokens", 0)),
            "completion_tokens": int(usage.get("output_tokens", len(times))),
        }
        usage_out["total_tokens"] = (
            usage_out["prompt_tokens"] + usage_out["completion_tokens"]
        )
        extension = {
            "metrics": metrics,
            "receipt": receipt,
            "registry_hash": REGISTRY_HASH.hex(),
            "attestation_grade": receipt["attestation"]["grade"],
            "settlement": {"metered": False, "access": access_mode},
            "provider_sees_plaintext": True,
            "inference_verifiable": False,
        }
        if req.stream:
            yield _sse(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": CLAUDE_MODEL,
                    "choices": [{"index": 0, "finish_reason": "stop", "delta": {}}],
                    "usage": usage_out,
                    "x_vinfer": extension,
                }
            )
            yield _sse("[DONE]")
        else:
            yield json.dumps(
                {
                    "id": completion_id,
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": CLAUDE_MODEL,
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": text},
                        }
                    ],
                    "usage": usage_out,
                    "x_vinfer": extension,
                }
            )

    if req.stream:
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, no-transform, private",
                "X-Accel-Buffering": "no",
            },
        )
    chunks = [chunk async for chunk in generate()]
    return JSONResponse(json.loads(chunks[-1]))


@app.get("/v1/receipts/{receipt_id}")
async def get_receipt(receipt_id: str):
    receipt = app.state.receipts.get(receipt_id)
    if receipt is None:
        raise HTTPException(404, "unknown receipt")
    return receipt
