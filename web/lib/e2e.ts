import { Chacha20Poly1305 } from "@hpke/chacha20poly1305";
import { CipherSuite, HkdfSha256 } from "@hpke/core";
import { DhkemX25519HkdfSha256 } from "@hpke/dhkem-x25519";

const encoder = new TextEncoder();
const EMPTY_AAD = new Uint8Array();
const HPKE_INFO = encoder.encode("verified-inference/hpke/v1");
const SESSION_CONTEXT = encoder.encode("vinfer/session/v1");

const suite = new CipherSuite({
  kem: new DhkemX25519HkdfSha256(),
  kdf: new HkdfSha256(),
  aead: new Chacha20Poly1305(),
});

function bytesFromBase64(value: string): Uint8Array {
  const raw = atob(value);
  return Uint8Array.from(raw, (character) => character.charCodeAt(0));
}

function base64FromBytes(value: ArrayBuffer | Uint8Array): string {
  const bytes = value instanceof Uint8Array ? value : new Uint8Array(value);
  let raw = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    raw += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(raw);
}

export interface SealedPayload {
  resp_nonce: string;
  sealed_response: string;
}

export interface SealedSession {
  enc: string;
  ciphertext: string;
  open(payload: SealedPayload): Promise<Uint8Array>;
}

export async function createSealedSession(
  enclavePublicKeyBase64: string,
  plaintext: Uint8Array,
): Promise<SealedSession> {
  const publicKeyBytes = bytesFromBase64(enclavePublicKeyBase64);
  if (publicKeyBytes.length !== 32) {
    throw new Error("attested HPKE key has an invalid length");
  }

  const recipientPublicKey = await suite.kem.deserializePublicKey(publicKeyBytes);
  const sender = await suite.createSenderContext({
    recipientPublicKey,
    info: HPKE_INFO,
  });
  const sessionKey = new Uint8Array(await sender.export(SESSION_CONTEXT, 32));
  const ciphertext = await sender.seal(plaintext, EMPTY_AAD);
  const responseCipher = new Chacha20Poly1305().createEncryptionContext(sessionKey);

  return {
    enc: base64FromBytes(sender.enc),
    ciphertext: base64FromBytes(ciphertext),
    async open(payload) {
      const plaintextBuffer = await responseCipher.open(
        bytesFromBase64(payload.resp_nonce),
        bytesFromBase64(payload.sealed_response),
        EMPTY_AAD,
      );
      return new Uint8Array(plaintextBuffer);
    },
  };
}
