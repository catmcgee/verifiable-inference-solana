"""Attestation-gated end-to-end sealed session.

After the client has VERIFIED the attestation (see cli/attest_verify.py) and thus
trusts the enclave's HPKE public key, it opens a session:

  client: create_sender_context(attested_enclave_pubkey) -> (enc, sctx)
          session_key = sctx.export("vinfer/session/v1", 32)
          sealed_prompt = HPKE seal(prompt)
          -> send {enc, sealed_prompt}
  server: recipient ctx from (enc, enclave_priv) -> open(sealed_prompt) = prompt
          session_key = rctx.export("vinfer/session/v1", 32)   # SAME key
          run inference, then AEAD-encrypt the RESPONSE under session_key
          -> return {resp_nonce, sealed_response}
  client: AEAD-decrypt sealed_response under session_key

Both directions are encrypted under a key that only the client and the attested
enclave share — the TLS-terminating operator sees ciphertext both ways. This
module is transport-agnostic; trust comes from verifying the attestation BEFORE
calling establish_* (a key you didn't verify buys nothing).
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from pyhpke import KEMKey

from server.crypto.hpke_box import INFO, SUITE

SESSION_EXPORT_CTX = b"vinfer/session/v1"


def _aead_seal(key: bytes, plaintext: bytes, aad: bytes = b"") -> tuple[str, str]:
    nonce = os.urandom(12)
    ct = ChaCha20Poly1305(key).encrypt(nonce, plaintext, aad)
    return base64.b64encode(nonce).decode(), base64.b64encode(ct).decode()


def _aead_open(key: bytes, nonce_b64: str, ct_b64: str, aad: bytes = b"") -> bytes:
    return ChaCha20Poly1305(key).decrypt(
        base64.b64decode(nonce_b64), base64.b64decode(ct_b64), aad)


# ---- client side ----
def client_open_session(enclave_pub_b64: str, prompt: bytes, aad: bytes = b"") -> tuple[dict, bytes]:
    """Returns (wire_dict_to_send, session_key). Call ONLY after verifying the
    attestation that vouched for enclave_pub_b64."""
    pub = KEMKey.from_pyca_cryptography_key(
        X25519PublicKey.from_public_bytes(base64.b64decode(enclave_pub_b64)))
    enc, sctx = SUITE.create_sender_context(pub, info=INFO)
    session_key = sctx.export(SESSION_EXPORT_CTX, 32)
    sealed_prompt = sctx.seal(prompt, aad=aad)
    return ({"enc": base64.b64encode(enc).decode(),
             "ciphertext": base64.b64encode(sealed_prompt).decode()}, session_key)


def client_open_response(session_key: bytes, resp_nonce_b64: str, sealed_response_b64: str,
                         aad: bytes = b"") -> bytes:
    return _aead_open(session_key, resp_nonce_b64, sealed_response_b64, aad)


# ---- server side (inside the enclave) ----
class ServerSession:
    """Derived from the enclave HPKE key + the client's enc; opens the prompt and
    seals the response under the shared exporter session key."""

    def __init__(self, enclave_hpke_key, enc_b64: str):
        self._rctx = SUITE.create_recipient_context(
            base64.b64decode(enc_b64), enclave_hpke_key._key, info=INFO)
        self.session_key = self._rctx.export(SESSION_EXPORT_CTX, 32)

    def open_prompt(self, ciphertext_b64: str, aad: bytes = b"") -> bytes:
        return self._rctx.open(base64.b64decode(ciphertext_b64), aad=aad)

    def seal_response(self, plaintext: bytes, aad: bytes = b"") -> dict:
        nonce_b64, ct_b64 = _aead_seal(self.session_key, plaintext, aad)
        return {"resp_nonce": nonce_b64, "sealed_response": ct_b64}
