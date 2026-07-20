"""One OpenAI-compatible response shape for every backend."""

from __future__ import annotations

import json
import time

from fastapi.responses import JSONResponse


STREAM_HEADERS = {
    "Cache-Control": "no-store, no-transform, private",
    "X-Accel-Buffering": "no",
}


def sse(payload: dict | str) -> str:
    value = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, separators=(",", ":"))
    )
    return f"data: {value}\n\n"


def stream_chunk(
    completion_id: str,
    model: str,
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    usage: dict | None = None,
    extension: dict | None = None,
) -> dict:
    body = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "delta": {"content": content} if content is not None else {},
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    if extension is not None:
        body["x_vinfer"] = extension
    return body


def completion_body(
    completion_id: str,
    model: str,
    text: str,
    finish_reason: str,
    usage: dict,
    extension: dict,
) -> dict:
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": text},
            }
        ],
        "usage": usage,
        "x_vinfer": extension,
    }


def response_with_receipt(body: dict, receipt: dict) -> JSONResponse:
    return JSONResponse(
        content=body, headers={"X-Vinfer-Receipt-Id": receipt["receipt_id"]}
    )
