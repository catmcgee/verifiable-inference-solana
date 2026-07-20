"""Client-side attestation verification — the trust root for e2e encryption.

verify_attestation(doc) decides whether the enclave's HPKE key can be trusted:

  1. report_data binding: report_data == sha256(enclave_pubkey ‖ registry_hash ‖
     build_hash). Cheap, always checked — proves the doc is internally consistent
     and the enclave signing key is bound to the declared registry + build.
     The HPKE key is separately domain-separated and signed by that key.
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
import json
import struct
from dataclasses import dataclass
from pathlib import Path

from nacl.signing import VerifyKey

from server.receipts.signer import HPKE_BINDING_DOMAIN


@dataclass
class Verdict:
    trusted: bool
    grade: str
    binding_ok: bool
    kds_ok: bool | None  # None = not applicable (no SNP report)
    reason: str


POLICY_PATH = Path(__file__).resolve().parents[1] / "attestation-policy.json"


def _load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text())


def _verify_snp_policy(report: bytes, doc: dict, policy: dict) -> tuple[bool, str]:
    version = struct.unpack_from("<I", report, 0x00)[0]
    guest_policy = struct.unpack_from("<Q", report, 0x08)[0]
    vmpl = struct.unpack_from("<I", report, 0x30)[0]
    sig_algo = struct.unpack_from("<I", report, 0x34)[0]
    measurement = report[0x90:0xC0].hex()
    reported_tcb = list(report[0x180:0x188])

    if version not in policy["allowed_report_versions"]:
        return False, f"SNP report version {version} is not allowed"
    if vmpl not in policy["allowed_vmpl"]:
        return False, f"VMPL {vmpl} is not allowed"
    if sig_algo != 1:
        return False, f"unsupported SNP signature algorithm {sig_algo}"
    if policy.get("require_debug_disabled", True) and guest_policy & (1 << 19):
        return False, "SNP guest policy permits debugging"
    if report[0x70:0x90] != bytes(32):
        return False, "upper half of REPORT_DATA must be zero"
    if measurement not in policy["allowed_measurements"]:
        return False, f"unapproved SNP launch measurement {measurement}"
    if doc.get("snp_measurement") not in (None, measurement):
        return False, "attestation document measurement does not match the report"
    execution_mode = (doc.get("execution") or {}).get("mode", "guest-declared")
    approved_build = next(
        (
            item
            for item in policy.get("allowed_builds", [])
            if item.get("measurement") == measurement
            and item.get("server_build_hash") == doc.get("server_build_hash")
            and item.get("execution_mode") == execution_mode
        ),
        None,
    )
    if approved_build is None:
        return (
            False,
            "measurement/build hash/execution-mode tuple is not approved by policy",
        )

    minimum = policy["minimum_reported_tcb"]
    # Turin TCB layout: FMC, bootloader, TEE, SNP, reserved x3, microcode.
    indexes = {"fmc": 0, "bootloader": 1, "tee": 2, "snp": 3, "microcode": 7}
    for name, index in indexes.items():
        if reported_tcb[index] < minimum[name]:
            return (
                False,
                f"reported TCB {name}={reported_tcb[index]} is below {minimum[name]}",
            )
    return True, (
        f"exact measurement/build pair approved for {execution_mode}; VMPL={vmpl}; "
        "debug disabled; TCB floor satisfied"
    )


def _verify_execution_identity(doc: dict) -> tuple[bool, str]:
    execution = doc.get("execution") or {"mode": "guest-declared", "manifest": None}
    mode = execution.get("mode", "guest-declared")
    if mode == "guest-declared":
        runtime = doc.get("runtime_version")
        if runtime and hashlib.sha256(runtime.encode()).hexdigest() != doc.get(
            "server_build_hash"
        ):
            return (
                False,
                "runtime_version does not reproduce the guest-declared build hash",
            )
        return True, "guest-declared build identity; no immutable userspace claim"
    if mode != "snp-measured-dm-verity":
        return False, f"unknown execution mode {mode!r}"
    manifest = execution.get("manifest")
    if not isinstance(manifest, dict):
        return False, "measured execution identity has no manifest"
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != doc.get("server_build_hash"):
        return False, "execution manifest does not reproduce server_build_hash"
    if manifest.get("mode") != mode:
        return False, "execution manifest mode mismatch"
    if manifest.get("runtime_version") != doc.get("runtime_version"):
        return False, "execution manifest runtime_version mismatch"
    if manifest.get("registry_hash") != doc.get("registry_hash"):
        return False, "execution manifest registry_hash mismatch"
    return True, "canonical measured-boot/dm-verity manifest matches build and registry"


def _report_data_expected(doc: dict) -> str:
    binding_version = int(doc.get("binding_version", 1))
    if binding_version == 1:
        identity_hash = doc["model_weights_hash"]
    elif binding_version == 2:
        identity_hash = doc["registry_hash"]
    else:
        raise ValueError(f"unsupported binding_version {binding_version}")
    return hashlib.sha256(
        base64.b64decode(doc["enclave_pubkey_b64"])
        + bytes.fromhex(identity_hash)
        + bytes.fromhex(doc["server_build_hash"])
    ).hexdigest()


def _verify_hpke_binding(doc: dict) -> tuple[bool, str]:
    try:
        hpke_public_key = base64.b64decode(doc["hpke_public_key_b64"], validate=True)
        signature = base64.b64decode(doc["hpke_binding_signature_b64"], validate=True)
        enclave_public_key = base64.b64decode(doc["enclave_pubkey_b64"], validate=True)
        if (
            len(hpke_public_key) != 32
            or len(signature) != 64
            or len(enclave_public_key) != 32
        ):
            return False, "HPKE binding has an invalid key or signature length"
        VerifyKey(enclave_public_key).verify(
            HPKE_BINDING_DOMAIN + hpke_public_key, signature
        )
        return True, "HPKE key is signed by the SNP-bound Ed25519 key"
    except KeyError:
        return False, "attestation document is missing the signed HPKE binding"
    except Exception as exc:  # noqa: BLE001
        return False, f"HPKE key binding is invalid: {type(exc).__name__}"


def verify_attestation(
    doc: dict,
    allow_unattested: bool = False,
    *,
    require_hpke: bool = True,
) -> Verdict:
    grade = doc.get("grade", "unknown")
    try:
        binding_ok = _report_data_expected(doc) == doc.get("report_data")
    except Exception as exc:  # noqa: BLE001
        return Verdict(
            False,
            grade,
            False,
            None,
            f"malformed attestation binding: {type(exc).__name__}",
        )
    if not binding_ok:
        return Verdict(
            False,
            grade,
            False,
            None,
            "report_data does not match the declared attestation binding "
            "— the doc is inconsistent; do NOT trust the key",
        )

    execution_ok, execution_why = _verify_execution_identity(doc)
    if not execution_ok:
        return Verdict(False, grade, True, None, execution_why)

    if require_hpke:
        hpke_ok, key_why = _verify_hpke_binding(doc)
        if not hpke_ok:
            return Verdict(False, grade, True, None, key_why)
    else:
        key_why = "component identity does not expose an HPKE key"

    if grade == "snp":
        rep = doc.get("snp_report_b64")
        if not rep:
            return Verdict(
                False, grade, True, False, "grade=snp but no snp_report_b64 present"
            )
        ok, why = _verify_snp_report(base64.b64decode(rep), doc["report_data"], doc)
        return Verdict(
            ok,
            grade,
            True,
            ok,
            "SNP report verified → VCEK → AMD KDS; " + execution_why + "; " + key_why
            if ok
            else f"SNP report verification failed: {why}",
        )

    if grade in ("launch-only", "none"):
        capability = (
            "the encryption is real but a remote party cannot verify the enclave"
            if require_hpke
            else "this component identity does not expose an HPKE key and a remote "
            "party cannot verify the component"
        )
        return Verdict(
            allow_unattested,
            grade,
            True,
            None,
            f"grade={grade}: binding holds but there is NO signed hardware report — "
            f"{capability}. "
            + (
                "proceeding because --insecure-allow-unattested was set"
                if allow_unattested
                else "refusing e2e session; rerun with --insecure-allow-unattested to "
                "accept an unattested enclave (dev/SEV-ES)"
            ),
        )

    return Verdict(False, grade, True, None, f"unknown grade {grade!r}")


def _verify_snp_report(
    report: bytes, expected_report_data_hex: str, doc: dict | None = None
) -> tuple[bool, str]:
    """Verify an SNP attestation report: REPORT_DATA field + signature → VCEK →
    AMD KDS (ASK/ARK). Uses `snpguest`/`sev-snp-measure`-style checks via the
    `cryptography` lib. Kept dependency-light; when SNP guests boot this runs for
    real against ~/vms/snp-report.bin. Layout per AMD SEV-SNP ABI:
       report_data at offset 0x50 (64 bytes); signature at 0x2A0 (ecdsa-p384)."""
    try:
        if len(report) < 0x2A0 + 96:
            return False, f"report too short ({len(report)} bytes)"
        report_data = report[0x50 : 0x50 + 64]
        # doc.report_data is our 32-byte sha256, placed in the low 32 bytes of the
        # 64-byte REPORT_DATA field (high 32 zero-padded).
        if report_data[:32].hex() != expected_report_data_hex:
            return False, "REPORT_DATA field != attestation doc report_data"
        # signature chain: VCEK (per-chip) signs the report; VCEK cert chains to
        # ASK → ARK (AMD roots). Fetch VCEK from KDS by the report's chip_id +
        # TCB, verify the ECDSA-P384 signature over report[0:0x2A0].
        from cli.kds import verify_vcek_chain

        chain_ok, chain_why = verify_vcek_chain(report)
        if not chain_ok:
            return False, chain_why
        if doc is None:
            doc = {
                "server_build_hash": _load_policy()["allowed_server_build_hashes"][0],
                "snp_measurement": report[0x90:0xC0].hex(),
            }
        policy_ok, policy_why = _verify_snp_policy(report, doc, _load_policy())
        if not policy_ok:
            return False, policy_why
        return True, f"{chain_why}; {policy_why}"
    except ImportError:
        return False, "kds verifier not available (install cryptography, requests)"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
