"""Mock attestation document.

Standing rule from PLAN.md: never fake an attestation grade. This module is
explicit about being grade "mock" — no hardware report exists. The REPORT_DATA
binding convention matches what the real SNP path will use:
    sha256(enclave_pubkey || model_weights_hash || server_build_hash)
so the verify pipeline exercises the same shape end-to-end before P3.
"""

from __future__ import annotations

import base64
import hashlib


def build_attestation(enclave_pubkey_b64: str, model_weights_hash: bytes, server_build_hash: bytes) -> dict:
    report_data = hashlib.sha256(
        base64.b64decode(enclave_pubkey_b64) + model_weights_hash + server_build_hash
    ).digest()
    return {
        "grade": "mock",
        "enclave_pubkey_b64": enclave_pubkey_b64,
        "report_data": report_data.hex(),
        "model_weights_hash": model_weights_hash.hex(),
        "server_build_hash": server_build_hash.hex(),
        "snp_measurement": None,
        "vcek_chain": None,
        "note": (
            "MOCK attestation: no hardware report. Real grade (snp | launch-only) "
            "is decided by the P1 recon gate. A verifier can conclude nothing from this."
        ),
    }
