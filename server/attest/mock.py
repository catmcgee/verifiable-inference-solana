"""Mock attestation document — binding v2 (ADDON step 3).

Never fakes a grade. REPORT_DATA convention (identical shape to the real SNP
path in P3, so the verify pipeline exercises the same bytes end to end):

    v2: sha256(enclave_pubkey || registry_hash || server_build_hash)
    v1 (legacy, PLAN.md): sha256(enclave_pubkey || model_weights_hash || build_hash)

The doc carries binding_version so `vinfer verify` checks — and prints — the
right one. New attestations are always v2; v1 remains verifiable for old
receipts only.
"""

from __future__ import annotations

import base64
import hashlib


def build_attestation(
    enclave_pubkey_b64: str,
    registry_hash: bytes,
    server_build_hash: bytes,
    registry: list[dict] | None = None,
) -> dict:
    report_data = hashlib.sha256(
        base64.b64decode(enclave_pubkey_b64) + registry_hash + server_build_hash
    ).digest()
    return {
        "grade": "mock",
        "binding_version": 2,
        "enclave_pubkey_b64": enclave_pubkey_b64,
        "report_data": report_data.hex(),
        "registry_hash": registry_hash.hex(),
        "registry": registry or [],
        "server_build_hash": server_build_hash.hex(),
        "snp_measurement": None,
        "vcek_chain": None,
        "note": (
            "MOCK attestation: no hardware report. Real grade (snp | launch-only) "
            "is decided by the P3 pipeline. A verifier can conclude nothing from this."
        ),
    }
