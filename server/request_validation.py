"""Shared limits for public inference request bodies."""

from __future__ import annotations


MAX_MESSAGES = 128
MAX_MESSAGE_CHARS = 524_288
MAX_CIPHERTEXT_CHARS = 900_000


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
