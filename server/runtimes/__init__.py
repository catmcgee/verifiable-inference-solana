"""Runtime adapters: each runtime implements the shared Runtime contract."""

from server.registry import ModelEntry
from server.runtimes.base import Runtime
from server.runtimes.bitnetcpp import BitnetCppRuntime
from server.runtimes.llamacpp import LlamaCppRuntime

_RUNTIMES: dict[str, type[Runtime]] = {
    "llamacpp": LlamaCppRuntime,
    "bitnetcpp": BitnetCppRuntime,
}


def for_model(entry: ModelEntry) -> Runtime:
    try:
        return _RUNTIMES[entry.runtime](entry)
    except KeyError:
        raise ValueError(
            f"unknown runtime {entry.runtime!r} for model {entry.id}"
        ) from None
