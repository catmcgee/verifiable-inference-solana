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
from fastapi.responses import StreamingResponse

from server import access, openai, registry
from server.attest.report import build_attestation, ensure_snp_report
from server.execution import load_identity
from server.receipts.issue import issue_receipt
from server.receipts.request_hash import canonical_request
from server.receipts.signer import EnclaveSigner
from server.receipts.store import ReceiptStore
from server.request_validation import ChatRequest


UPSTREAM = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = os.environ.get("VINFER_C_MODEL", "claude-haiku-4-5-20251001")
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
PROXY_BUILD = "vinfer-legc-proxy-0.2.2"
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
    app.state.receipts = ReceiptStore()
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
    version="0.2.2",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.include_router(access.router)


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
    return await issue_receipt(
        signer=app.state.signer,
        prompt=prompt,
        text=text,
        model_hash=bytes.fromhex(MODEL_DECLARATION_HASH),
        metrics=metrics,
        attestation=lambda: _attestation_doc(app),
        receipts=app.state.receipts,
    )


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
                            yield openai.sse(
                                openai.stream_chunk(
                                    completion_id, CLAUDE_MODEL, content=text
                                )
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
            yield openai.sse(
                openai.stream_chunk(
                    completion_id,
                    CLAUDE_MODEL,
                    finish_reason="stop",
                    usage=usage_out,
                    extension=extension,
                )
            )
            yield openai.sse("[DONE]")
        else:
            yield openai.completion_body(
                completion_id, CLAUDE_MODEL, text, "stop", usage_out, extension
            )

    if req.stream:
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers=openai.STREAM_HEADERS,
        )
    chunks = [chunk async for chunk in generate()]
    body = chunks[-1]
    return openai.response_with_receipt(body, body["x_vinfer"]["receipt"])


@app.get("/v1/receipts/{receipt_id}")
async def get_receipt(receipt_id: str):
    receipt = app.state.receipts.get(receipt_id)
    if receipt is None:
        raise HTTPException(404, "unknown receipt")
    return receipt
