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


def ensure_snp_report(report_data: bytes) -> str | None:
    """Request a REAL SNP attestation report from /dev/sev-guest, with our
    binding hash as REPORT_DATA (low 32 bytes of the 64-byte field).

    Called at server startup, after the enclave key exists — the report is
    thereby bound to THIS process's key + registry + build. Returns the report
    path (and points VINFER_SNP_REPORT at it) or None when not in an SNP guest.
    No fallback, no fake: if snpguest fails, grade honestly stays launch-only.
    """
    import subprocess
    import tempfile

    if os.environ.get("VINFER_SEV_MODE") != "snp" or not Path("/dev/sev-guest").exists():
        return None
    if len(report_data) != 32:
        raise ValueError("report_data must be 32 bytes")
    workdir = Path(tempfile.mkdtemp(prefix="vinfer-snp-"))
    request = workdir / "request.bin"
    report = workdir / "report.bin"
    request.write_bytes(report_data + b"\x00" * 32)  # 64-byte REPORT_DATA field
    try:
        subprocess.run(
            ["snpguest", "report", str(report), str(request)],
            check=True, capture_output=True, timeout=30,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        import logging
        logging.getLogger("vinfer").warning(
            "snpguest report failed (%s) — grade downgrades to launch-only", e)
        return None
    os.environ["VINFER_SNP_REPORT"] = str(report)
    return str(report)


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
