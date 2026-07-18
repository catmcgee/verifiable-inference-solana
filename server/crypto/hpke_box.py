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

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
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

    def open(self, enc_b64: str, ciphertext_b64: str, aad: bytes = b"") -> bytes:
        enc = base64.b64decode(enc_b64)
        ct = base64.b64decode(ciphertext_b64)
        recipient = SUITE.create_recipient_context(enc, self._key, info=INFO)
        return recipient.open(ct, aad=aad)


def seal_to_enclave(enclave_pub_b64: str, plaintext: bytes, aad: bytes = b"") -> dict:
    """Client-side: encrypt a prompt to the enclave's HPKE public key."""
    pub = KEMKey.from_pyca_cryptography_key(
        X25519PublicKey.from_public_bytes(base64.b64decode(enclave_pub_b64))
    )
    enc, sender = SUITE.create_sender_context(pub, info=INFO)
    ct = sender.seal(plaintext, aad=aad)
    return {
        "enc": base64.b64encode(enc).decode(),
        "ciphertext": base64.b64encode(ct).decode(),
    }
