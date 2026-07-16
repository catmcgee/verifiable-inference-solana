"""Receipt signing with an in-memory enclave key.

Standing rule: the enclave signing key is generated at process start and never
persisted. The signed message layout must stay byte-identical to what the
Solana program's ed25519 introspection checks:

    prompt_hash(32) || response_hash(32) || model_hash(32) || timestamp_le(8, i64)
"""

from __future__ import annotations

import base64
import hashlib
import struct
import time
import uuid

from nacl.signing import SigningKey, VerifyKey


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def receipt_message(prompt_hash: bytes, response_hash: bytes, model_hash: bytes, timestamp: int) -> bytes:
    if not (len(prompt_hash) == len(response_hash) == len(model_hash) == 32):
        raise ValueError("hashes must be 32 bytes")
    return prompt_hash + response_hash + model_hash + struct.pack("<q", timestamp)


class EnclaveSigner:
    def __init__(self) -> None:
        self._key = SigningKey.generate()
        self.created_at = int(time.time())

    @property
    def pubkey_b64(self) -> str:
        return base64.b64encode(bytes(self._key.verify_key)).decode()

    def sign_receipt(self, prompt: str, response: str, model_hash: bytes) -> dict:
        ts = int(time.time())
        prompt_hash = sha256(prompt.encode())
        response_hash = sha256(response.encode())
        msg = receipt_message(prompt_hash, response_hash, model_hash, ts)
        sig = self._key.sign(msg).signature
        return {
            "receipt_id": uuid.uuid4().hex[:16],
            "enclave_pubkey_b64": self.pubkey_b64,
            "prompt_hash": prompt_hash.hex(),
            "response_hash": response_hash.hex(),
            "model_hash": model_hash.hex(),
            "timestamp": ts,
            "sig_b64": base64.b64encode(sig).decode(),
        }


def verify_receipt(receipt: dict) -> bool:
    """Offline ed25519 verification of a receipt dict (raises on malformed input)."""
    msg = receipt_message(
        bytes.fromhex(receipt["prompt_hash"]),
        bytes.fromhex(receipt["response_hash"]),
        bytes.fromhex(receipt["model_hash"]),
        int(receipt["timestamp"]),
    )
    vk = VerifyKey(base64.b64decode(receipt["enclave_pubkey_b64"]))
    try:
        vk.verify(msg, base64.b64decode(receipt["sig_b64"]))
        return True
    except Exception:
        return False
