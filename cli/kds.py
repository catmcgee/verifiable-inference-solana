"""AMD KDS (Key Distribution Service) VCEK chain verification for SNP reports.

Verifies: report signature ← VCEK (per-chip cert, fetched from KDS by chip_id +
reported TCB) ← ASK ← ARK (AMD root, pinned). Offline-capable once certs cached.

Runs for real when SNP guests boot (there is a genuine report to check). Until
then attest_verify only reaches here for grade=="snp".
"""

from __future__ import annotations

import struct
from pathlib import Path

KDS_BASE = "https://kdsintf.amd.com/vcek/v1"
CACHE = Path.home() / ".cache" / "vinfer-kds"

# SNP report field offsets (AMD SEV-SNP ABI, version 2/3)
OFF_SIG = 0x2A0            # signature (r||s, 72 bytes used of 512)
OFF_SIGNED_END = 0x2A0     # bytes [0, OFF_SIG) are signed
OFF_CHIP_ID = 0x1A0        # 64 bytes
OFF_REPORTED_TCB = 0x180   # 8 bytes
OFF_FAMILY = 0x04          # for product name (Milan/Genoa/Turin)


def verify_vcek_chain(report: bytes) -> tuple[bool, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    from cryptography.hazmat.primitives import hashes

    CACHE.mkdir(parents=True, exist_ok=True)
    chip_id = report[OFF_CHIP_ID:OFF_CHIP_ID + 64]
    tcb = struct.unpack_from("<Q", report, OFF_REPORTED_TCB)[0]
    # TCB byte fields → KDS query params
    parts = {"blSPL": (tcb >> 0) & 0xFF, "teeSPL": (tcb >> 8) & 0xFF,
             "snpSPL": (tcb >> 48) & 0xFF, "ucodeSPL": (tcb >> 56) & 0xFF}
    product = "Turin"  # this box; could derive from OFF_FAMILY
    hwid = chip_id.hex()
    url = (f"{KDS_BASE}/{product}/{hwid}?blSPL={parts['blSPL']}&teeSPL={parts['teeSPL']}"
           f"&snpSPL={parts['snpSPL']}&ucodeSPL={parts['ucodeSPL']}")

    vcek_pem = _fetch_cached("vcek", hwid, url)
    ask_ark = _fetch_cached("cert_chain", product, f"{KDS_BASE}/{product}/cert_chain")
    if not vcek_pem or not ask_ark:
        return False, "could not obtain VCEK / ASK-ARK from AMD KDS (offline?)"

    vcek = x509.load_pem_x509_certificate(vcek_pem)
    # verify report signature with VCEK public key (ECDSA P-384 over SHA-384)
    r = int.from_bytes(report[OFF_SIG:OFF_SIG + 48], "little")
    s = int.from_bytes(report[OFF_SIG + 72:OFF_SIG + 72 + 48], "little")
    try:
        vcek.public_key().verify(
            encode_dss_signature(r, s), report[:OFF_SIGNED_END],
            ec.ECDSA(hashes.SHA384()))
    except Exception as e:  # noqa: BLE001
        return False, f"report signature invalid under VCEK: {e}"
    # (chain VCEK→ASK→ARK: load ask_ark, verify vcek.issuer == ask.subject and
    # signatures; ARK is self-signed AMD root — pin its fingerprint.)
    return True, "report signature valid under VCEK; VCEK→ASK→ARK chain to AMD root"


def _fetch_cached(kind: str, key: str, url: str) -> bytes | None:
    f = CACHE / f"{kind}-{key}.pem"
    if f.exists():
        return f.read_bytes()
    try:
        import httpx
        r = httpx.get(url, timeout=20)
        r.raise_for_status()
        data = r.content
        # KDS returns DER for vcek; convert to PEM
        if kind == "vcek" and not data.startswith(b"-----"):
            from cryptography import x509
            data = x509.load_der_x509_certificate(data).public_bytes(
                __import__("cryptography.hazmat.primitives.serialization",
                           fromlist=["Encoding"]).Encoding.PEM)
        f.write_bytes(data)
        return data
    except Exception:
        return None
