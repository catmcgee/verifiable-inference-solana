from __future__ import annotations

from abc import ABC, abstractmethod

from server.registry import ModelEntry


class Runtime(ABC):
    """Adapter interface. generate() is the raw-prompt path (harness/bench);
    chat() is the OpenAI-shaped path (/v1/chat/completions). Both return the
    metrics dict shape the schema expects (client-measured TTFT/ITL)."""

    def __init__(self, entry: ModelEntry):
        self.entry = entry

    @abstractmethod
    async def generate(self, prompt: str, max_tokens: int) -> dict: ...

    @abstractmethod
    async def chat(self, messages: list[dict], max_tokens: int) -> dict: ...
