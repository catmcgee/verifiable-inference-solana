"""Client-side attestation verification — the trust root for e2e encryption.

verify_attestation(doc) decides whether the enclave's HPKE key can be trusted:

  1. report_data binding: report_data == sha256(enclave_pubkey ‖ registry_hash ‖
     build_hash). Cheap, always checked — proves the doc is internally consistent
     and the HPKE/enclave keys are bound to the served registry + build.
  2. grade gate:
       - "snp": parse the SNP report, verify its signature up the VCEK → AMD KDS
         (ASK/ARK) chain, and check the report's REPORT_DATA field equals the
         doc's report_data. THIS is what makes the key trustworthy end to end.
       - "launch-only" (SEV/SEV-ES): binding holds but there is NO hardware
         proof — return trusted=False with a clear reason; the caller may proceed
         only under an explicit --insecure-allow-unattested.
       - "none": not trustworthy (no TEE).

Returns a Verdict; the e2e client refuses to send a sealed prompt unless the key
is trusted (or the user explicitly overrode).
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass


@dataclass
class Verdict:
    trusted: bool
    grade: str
    binding_ok: bool
    kds_ok: bool | None       # None = not applicable (no SNP report)
    reason: str


def _report_data_expected(doc: dict) -> str:
    return hashlib.sha256(
        base64.b64decode(doc["enclave_pubkey_b64"])
        + bytes.fromhex(doc["registry_hash"])
        + bytes.fromhex(doc["server_build_hash"])
    ).hexdigest()


def verify_attestation(doc: dict, allow_unattested: bool = False) -> Verdict:
    grade = doc.get("grade", "unknown")
    binding_ok = _report_data_expected(doc) == doc.get("report_data")
    if not binding_ok:
        return Verdict(False, grade, False, None,
                       "report_data != sha256(enclave_pubkey‖registry_hash‖build) "
                       "— the doc is inconsistent; do NOT trust the key")

    if grade == "snp":
        rep = doc.get("snp_report_b64")
        if not rep:
            return Verdict(False, grade, True, False,
                           "grade=snp but no snp_report_b64 present")
        ok, why = _verify_snp_report(base64.b64decode(rep), doc["report_data"])
        return Verdict(ok, grade, True, ok,
                       "SNP report verified → VCEK → AMD KDS; key is hardware-attested"
                       if ok else f"SNP report verification failed: {why}")

    if grade in ("launch-only", "none"):
        return Verdict(
            allow_unattested, grade, True, None,
            f"grade={grade}: binding holds but there is NO signed hardware report — "
            "the encryption is real but a remote party cannot verify the enclave. "
            + ("proceeding because --insecure-allow-unattested was set"
               if allow_unattested else
               "refusing e2e session; rerun with --insecure-allow-unattested to "
               "accept an unattested enclave (dev/SEV-ES)"))

    return Verdict(False, grade, True, None, f"unknown grade {grade!r}")


def _verify_snp_report(report: bytes, expected_report_data_hex: str) -> tuple[bool, str]:
    """Verify an SNP attestation report: REPORT_DATA field + signature → VCEK →
    AMD KDS (ASK/ARK). Uses `snpguest`/`sev-snp-measure`-style checks via the
    `cryptography` lib. Kept dependency-light; when SNP guests boot this runs for
    real against ~/vms/snp-report.bin. Layout per AMD SEV-SNP ABI:
       report_data at offset 0x50 (64 bytes); signature at 0x2A0 (ecdsa-p384)."""
    try:
        if len(report) < 0x2A0 + 96:
            return False, f"report too short ({len(report)} bytes)"
        report_data = report[0x50:0x50 + 64]
        # doc.report_data is our 32-byte sha256, placed in the low 32 bytes of the
        # 64-byte REPORT_DATA field (high 32 zero-padded).
        if report_data[:32].hex() != expected_report_data_hex:
            return False, "REPORT_DATA field != attestation doc report_data"
        # signature chain: VCEK (per-chip) signs the report; VCEK cert chains to
        # ASK → ARK (AMD roots). Fetch VCEK from KDS by the report's chip_id +
        # TCB, verify the ECDSA-P384 signature over report[0:0x2A0].
        from cli.kds import verify_vcek_chain
        return verify_vcek_chain(report)
    except ImportError:
        return False, "kds verifier not available (install cryptography, requests)"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
