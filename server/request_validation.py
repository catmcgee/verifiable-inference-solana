"""Shared limits for public inference request bodies."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


MAX_MESSAGES = 128
MAX_MESSAGE_CHARS = 524_288
MAX_CIPHERTEXT_CHARS = 900_000
MAX_OUTPUT_TOKENS = 8192


def validate_messages(messages: list[dict]) -> list[dict]:
    total_chars = 0
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"}:
            raise ValueError("each message must have a supported role")
        if not isinstance(content, str):
            raise ValueError("each message must contain text content")
        total_chars += len(content)
        if total_chars > MAX_MESSAGE_CHARS:
            raise ValueError("combined message content is too large")
    return messages


class ChatRequest(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    messages: list[dict] = Field(min_length=1, max_length=MAX_MESSAGES)
    max_tokens: int = Field(default=256, ge=1, le=MAX_OUTPUT_TOKENS)
    stream: bool = False

    _messages_are_valid = field_validator("messages")(validate_messages)
