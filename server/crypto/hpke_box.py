"""HPKE encrypt-to-enclave input mode (frozen schema input_mode=hpke).

The enclave holds an X25519 HPKE keypair generated at boot alongside its ed25519
signing key. A client fetches the enclave's HPKE public key from /v1/attestation;
the SNP-bound Ed25519 key signs it with a domain-separated binding signature,
encrypts the prompt to it, and the server decrypts *inside* the enclave — so the
proxy/operator on the TLS-terminating path never sees plaintext.

Suite: DHKEM(X25519, HKDF-SHA256) + HKDF-SHA256 + ChaCha20Poly1305 (base mode).
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from pyhpke import AEADId, CipherSuite, KDFId, KEMId, KEMKey

SUITE = CipherSuite.new(
    KEMId.DHKEM_X25519_HKDF_SHA256,
    KDFId.HKDF_SHA256,
    AEADId.CHACHA20_POLY1305,
)
INFO = b"verified-inference/hpke/v1"


class EnclaveHpkeKey:
    """Enclave-side HPKE keypair. Private key never leaves the process."""

    def __init__(self) -> None:
        self._sk = X25519PrivateKey.generate()
        self._key = KEMKey.from_pyca_cryptography_key(self._sk)

    @property
    def public_key_b64(self) -> str:
        raw = self._sk.public_key().public_bytes_raw()
        return base64.b64encode(raw).decode()
