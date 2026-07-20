from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from server.registry import ModelEntry


class Runtime(ABC):
    """Common runtime contract for registry-selected model backends."""

    def __init__(self, entry: ModelEntry):
        self.entry = entry

    @abstractmethod
    async def load(self) -> None:
        """Fail unless this model's already-launched runtime is healthy."""

    async def chat(self, messages: list[dict], max_tokens: int) -> dict:
        result = None
        async for event in self.chat_stream(messages, max_tokens):
            if event["type"] == "done":
                result = event["result"]
        if result is None:
            raise RuntimeError("runtime stream ended without final metrics")
        return result

    @abstractmethod
    def chat_stream(
        self, messages: list[dict], max_tokens: int
    ) -> AsyncIterator[dict]: ...
