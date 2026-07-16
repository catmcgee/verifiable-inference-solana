"""Model registry loader — models.yaml is the single source of truth.

registry_hash (attestation binding v2) = sha256 over the sorted
"(model_id, weights_sha256)" pairs of SERVABLE entries (null-hash entries are
pending: listed in /v1/models as unavailable, excluded from the hash).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "models.yaml"


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
        if not self.servable:
            raise RuntimeError(f"model {self.id} is pending (no weights hash)")
        return bytes.fromhex(self.weights_sha256)


def load(path: Path = REGISTRY_PATH) -> dict[str, ModelEntry]:
    raw = yaml.safe_load(path.read_text())
    entries = {}
    for e in raw:
        entries[e["id"]] = ModelEntry(
            id=e["id"], runtime=e["runtime"], weights=e["weights"],
            weights_sha256=e.get("weights_sha256"), quant=e["quant"],
            ctx_max=e["ctx_max"], chat_template=e["chat_template"],
            legs=tuple(e["legs"]), port=e["port"],
            price_per_1m_in_usdc=e.get("price_per_1m_in_usdc"),
            price_per_1m_out_usdc=e.get("price_per_1m_out_usdc"),
        )
    return entries


def pairs_hash(pairs: list[dict]) -> bytes:
    """sha256 over sorted (model_id, weights_sha256) pairs (binding v2)."""
    ordered = sorted((p["id"], p["weights_sha256"]) for p in pairs)
    payload = "\n".join(f"{i} {h}" for i, h in ordered).encode()
    return hashlib.sha256(payload).digest()


def registry_hash(entries: dict[str, ModelEntry]) -> bytes:
    return pairs_hash(
        [{"id": m.id, "weights_sha256": m.weights_sha256} for m in entries.values() if m.servable]
    )
