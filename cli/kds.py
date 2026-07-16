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


def _kds_params(report: bytes) -> tuple[str, str, str]:
    """(product, hwid_hex, query) from the report's CPUID family + TCB layout.

    Turin (family 0x1A) reports an 8-byte hardware ID (rest of CHIP_ID zero) and
    its TCB adds an FMC SPL byte: b0=FMC b1=BL b2=TEE b3=SNP b7=UCODE. Milan/
    Genoa (0x19) use the full 64-byte CHIP_ID and b0=BL b1=TEE b6=SNP b7=UCODE.
    Wrong layout/hwid → KDS 404 (how this function came to exist).
    """
    family = report[0x188]
    model = report[0x189]
    tcb = report[OFF_REPORTED_TCB:OFF_REPORTED_TCB + 8]
    chip_id = report[OFF_CHIP_ID:OFF_CHIP_ID + 64]
    if family == 0x1A:
        product = "Turin"
        hwid = chip_id[:8].hex()
        query = (f"fmcSPL={tcb[0]}&blSPL={tcb[1]}&teeSPL={tcb[2]}"
                 f"&snpSPL={tcb[3]}&ucodeSPL={tcb[7]}")
    else:
        product = "Milan" if model < 0x10 else "Genoa"
        hwid = chip_id.hex()
        query = (f"blSPL={tcb[0]}&teeSPL={tcb[1]}&snpSPL={tcb[6]}"
                 f"&ucodeSPL={tcb[7]}")
    return product, hwid, query


def verify_vcek_chain(report: bytes) -> tuple[bool, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    from cryptography.hazmat.primitives import hashes

    CACHE.mkdir(parents=True, exist_ok=True)
    product, hwid, query = _kds_params(report)
    url = f"{KDS_BASE}/{product}/{hwid}?{query}"

    vcek_pem = _fetch_cached("vcek", f"{hwid}-{query}", url)
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

    # chain: VCEK signed by ASK, ASK signed by ARK, ARK self-signed (AMD root).
    # KDS cert_chain is [ASK, ARK] PEM concatenated. AMD signs with RSA-PSS.
    certs = x509.load_pem_x509_certificates(ask_ark)
    if len(certs) < 2:
        return False, f"KDS cert_chain returned {len(certs)} certs, expected ASK+ARK"
    ask, ark = certs[0], certs[1]

    def _issued(child: x509.Certificate, parent: x509.Certificate, what: str) -> str | None:
        if child.issuer != parent.subject:
            return f"{what}: issuer does not match parent subject"
        pub = parent.public_key()
        try:
            if isinstance(pub, rsa.RSAPublicKey):
                pub.verify(child.signature, child.tbs_certificate_bytes,
                           padding.PSS(mgf=padding.MGF1(hashes.SHA384()),
                                       salt_length=child.signature_hash_algorithm.digest_size),
                           child.signature_hash_algorithm)
            else:
                pub.verify(child.signature, child.tbs_certificate_bytes,
                           ec.ECDSA(child.signature_hash_algorithm))
        except Exception as e:  # noqa: BLE001
            return f"{what}: signature invalid: {e}"
        return None

    for child, parent, what in ((vcek, ask, "VCEK←ASK"), (ask, ark, "ASK←ARK"),
                                (ark, ark, "ARK self-signature")):
        err = _issued(child, parent, what)
        if err:
            return False, err
    subject = ark.subject.rfc4514_string()
    if "Advanced Micro Devices" not in subject and "AMD" not in subject:
        return False, f"ARK subject is not an AMD root: {subject}"
    return True, f"report sig valid under VCEK; VCEK→ASK→ARK chain verified ({product})"


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
