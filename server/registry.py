"""Model registry loader — models.yaml is the single source of truth.

registry_hash (attestation binding v2) = sha256 over the sorted
"(model_id, weights_sha256)" pairs of SERVABLE entries (null-hash entries are
pending: listed in /v1/models as unavailable, excluded from the hash).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "models.yaml"
MODEL_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")
RUNTIMES = frozenset({"llamacpp", "bitnetcpp"})
LEGS = frozenset({"A", "B", "D"})
CHAT_TEMPLATES = frozenset({"builtin", "bitnet", "jinja"})


@dataclass(frozen=True)
class ModelEntry:
    id: str
    runtime: str
    weights: str
    weights_sha256: str | None
    quant: str
    ctx_max: int
    chat_template: str
    legs: tuple[str, ...]
    port: int
    price_per_1m_in_usdc: float | None = None
    price_per_1m_out_usdc: float | None = None

    @property
    def servable(self) -> bool:
        return self.weights_sha256 is not None

    @property
    def weights_hash(self) -> bytes:
        digest = self.weights_sha256
        if digest is None:
            raise RuntimeError(f"model {self.id} is pending (no weights hash)")
        return bytes.fromhex(digest)


def load(path: Path = REGISTRY_PATH) -> dict[str, ModelEntry]:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path}: registry must be a non-empty YAML list")
    entries: dict[str, ModelEntry] = {}
    ports: set[int] = set()
    for e in raw:
        if not isinstance(e, dict):
            raise ValueError(f"{path}: every registry entry must be a mapping")
        model_id = e.get("id")
        if not isinstance(model_id, str) or not MODEL_ID.fullmatch(model_id):
            raise ValueError(f"{path}: invalid model id {model_id!r}")
        if model_id in entries:
            raise ValueError(f"{path}: duplicate model id {model_id!r}")
        runtime = e.get("runtime")
        if runtime not in RUNTIMES:
            raise ValueError(f"{path}: unsupported runtime {runtime!r} for {model_id}")
        weights = e.get("weights")
        if not isinstance(weights, str) or not Path(weights).is_absolute():
            raise ValueError(f"{path}: weights for {model_id} must be an absolute path")
        weights_sha256 = e.get("weights_sha256")
        if weights_sha256 is not None and (
            not isinstance(weights_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", weights_sha256)
        ):
            raise ValueError(f"{path}: invalid weights_sha256 for {model_id}")
        quant = e.get("quant")
        if not isinstance(quant, str) or not quant:
            raise ValueError(f"{path}: invalid quant for {model_id}")
        port = e.get("port")
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError(f"{path}: invalid port for {model_id}")
        if port in ports:
            raise ValueError(f"{path}: duplicate runtime port {port}")
        ports.add(port)
        ctx_max = e.get("ctx_max")
        if type(ctx_max) is not int or ctx_max <= 0:
            raise ValueError(f"{path}: ctx_max for {model_id} must be positive")
        chat_template = e.get("chat_template")
        if chat_template not in CHAT_TEMPLATES:
            raise ValueError(f"{path}: invalid chat_template for {model_id}")
        legs = e.get("legs")
        if (
            not isinstance(legs, list)
            or not legs
            or any(not isinstance(leg, str) for leg in legs)
            or len(set(legs)) != len(legs)
            or set(legs) - LEGS
        ):
            raise ValueError(f"{path}: invalid legs for {model_id}")
        prices = (e.get("price_per_1m_in_usdc"), e.get("price_per_1m_out_usdc"))
        if (prices[0] is None) != (prices[1] is None):
            raise ValueError(
                f"{path}: both prices must be present or absent for {model_id}"
            )
        if any(
            price is not None
            and (type(price) not in (int, float) or not 0 < price < float("inf"))
            for price in prices
        ):
            raise ValueError(f"{path}: prices for {model_id} must be positive")

        entries[model_id] = ModelEntry(
            id=model_id,
            runtime=runtime,
            weights=weights,
            weights_sha256=weights_sha256,
            quant=quant,
            ctx_max=ctx_max,
            chat_template=chat_template,
            legs=tuple(legs),
            port=port,
            price_per_1m_in_usdc=prices[0],
            price_per_1m_out_usdc=prices[1],
        )
    return entries


def servable_ids(entries: dict[str, ModelEntry]) -> list[str]:
    return [model.id for model in entries.values() if model.servable]


def pairs_hash(pairs: list[dict]) -> bytes:
    """sha256 over sorted (model_id, weights_sha256) pairs (binding v2)."""
    ordered = sorted((p["id"], p["weights_sha256"]) for p in pairs)
    payload = "\n".join(f"{i} {h}" for i, h in ordered).encode()
    return hashlib.sha256(payload).digest()


def registry_hash(entries: dict[str, ModelEntry]) -> bytes:
    return pairs_hash(
        [
            {"id": m.id, "weights_sha256": m.weights_sha256}
            for m in entries.values()
            if m.servable
        ]
    )
