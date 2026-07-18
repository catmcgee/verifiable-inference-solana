"""Local origin used only by the pay gateway integration test."""

from __future__ import annotations

import json

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse


app = FastAPI()


def _authorized(authorization: str | None) -> None:
    if authorization != "Bearer test-origin-token-for-local-pay-gateway":
        raise HTTPException(401, "bad origin credential")


@app.get("/v1/models")
async def models():
    return {"data": [{"id": "bitnet-2b", "status": "available"}]}


@app.get("/v1/attestation")
async def attestation():
    return {"grade": "none", "note": "payment integration fixture only"}


@app.post("/v1/chat/completions")
async def completions(body: dict, authorization: str | None = Header(default=None)):
    _authorized(authorization)
    model = body.get("model", "bitnet-2b")
    if not body.get("stream"):
        return {
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
            "x_vinfer": {
                "receipt": {"receipt_id": "payment-integration-fixture"},
                "attestation_grade": "none",
            },
        }

    async def events():
        yield (
            "data: "
            + json.dumps(
                {
                    "model": model,
                    "choices": [{"delta": {"content": "ok"}, "finish_reason": None}],
                }
            )
            + "\n\n"
        )
        yield (
            "data: "
            + json.dumps(
                {
                    "model": model,
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "usage": {
                        "prompt_tokens": 4,
                        "completion_tokens": 1,
                        "total_tokens": 5,
                    },
                    "x_vinfer": {
                        "receipt": {"receipt_id": "payment-integration-fixture"},
                        "attestation_grade": "none",
                    },
                }
            )
            + "\n\n"
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
