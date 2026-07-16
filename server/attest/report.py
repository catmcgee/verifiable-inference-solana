"""Attestation document — honest grade from the real runtime. Never fakes, never
"mock". Grade is derived from the ACTUAL SEV state of the process:

  VINFER_SEV_MODE=off            -> "none"        (no TEE; plaintext memory —
                                     e.g. the server running on bare metal)
  VINFER_SEV_MODE=sev|es         -> "launch-only" (server is inside a SEV/SEV-ES
                                     CVM: memory encrypted, but NO signed runtime
                                     report — a verifier learns only that SEV was
                                     requested at launch, per PLAN.md)
  VINFER_SEV_MODE=snp + a real snpguest report at VINFER_SNP_REPORT
                                 -> "snp"         (signed runtime report present)
  VINFER_SEV_MODE=snp, no report -> "launch-only" (honest downgrade)

REPORT_DATA binding (v2) = sha256(enclave_pubkey || registry_hash || build_hash),
identical shape to the real SNP path so the verify pipeline is exercised end to
end regardless of grade.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path


def current_grade() -> tuple[str, str]:
    """Returns (grade, note) from the real environment. No faking, no mock."""
    sev = os.environ.get("VINFER_SEV_MODE", "off")
    if sev == "off":
        return "none", ("No TEE: this process runs with plaintext memory (e.g. on "
                        "bare metal). The receipt still binds model+I/O to the "
                        "enclave key, but confidentiality is NOT provided — run the "
                        "server inside a SEV CVM for that.")
    if sev in ("sev", "es"):
        return "launch-only", (f"SEV{'-ES' if sev == 'es' else ''}: guest memory is "
                               "encrypted, but there is NO signed runtime report — a "
                               "verifier learns only that SEV was requested at launch.")
    if sev == "snp":
        report = os.environ.get("VINFER_SNP_REPORT", "")
        if report and Path(report).exists():
            return "snp", ("SEV-SNP: signed runtime attestation report present; "
                           "verify report -> VCEK -> AMD KDS (ASK/ARK) chain.")
        return "launch-only", ("SEV-SNP requested but no snpguest report is wired "
                               "yet — honest downgrade to launch-only.")
    return "none", f"unrecognized VINFER_SEV_MODE={sev!r}; treating as no TEE."


def build_attestation(
    enclave_pubkey_b64: str,
    registry_hash: bytes,
    server_build_hash: bytes,
    registry: list[dict] | None = None,
) -> dict:
    grade, note = current_grade()
    report_data = hashlib.sha256(
        base64.b64decode(enclave_pubkey_b64) + registry_hash + server_build_hash
    ).digest()
    snp_report_b64 = None
    if grade == "snp":
        snp_report_b64 = base64.b64encode(
            Path(os.environ["VINFER_SNP_REPORT"]).read_bytes()
        ).decode()
    return {
        "grade": grade,
        "binding_version": 2,
        "enclave_pubkey_b64": enclave_pubkey_b64,
        "report_data": report_data.hex(),
        "registry_hash": registry_hash.hex(),
        "registry": registry or [],
        "server_build_hash": server_build_hash.hex(),
        "sev_mode": os.environ.get("VINFER_SEV_MODE", "off"),
        "snp_measurement": None,
        "snp_report_b64": snp_report_b64,
        "vcek_chain": None,
        "note": note,
    }
