import "reflect-metadata";

import { X509Certificate } from "@peculiar/x509";
import { address, getProgramDerivedAddress, type Address } from "@solana/addresses";
import nacl from "tweetnacl";

import policy from "../../attestation-policy.json";
import type { AttestationDoc, Receipt } from "@/lib/api";
import { REGISTRY_PROGRAM } from "@/lib/labels";

const DEVNET_RPC = "https://api.devnet.solana.com";
const HPKE_DOMAIN = new TextEncoder().encode("vinfer-hpke-binding-v1\0");

type VerificationStatus = "pass" | "fail" | "absent" | "not-applicable";

interface VerificationCheck {
  id: string;
  label: string;
  status: VerificationStatus;
  detail: string;
}

export interface BrowserVerification {
  status: "verified" | "failed" | "incomplete";
  attestationTrusted: boolean;
  checks: VerificationCheck[];
  attestationPda?: string;
  receiptPda?: string;
}

function bytesFromB64(value: string): Uint8Array {
  const raw = atob(value);
  return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

function bytesFromHex(value: string): Uint8Array {
  if (!/^[0-9a-f]+$/i.test(value) || value.length % 2 !== 0) {
    throw new Error("invalid hexadecimal value");
  }
  return Uint8Array.from(value.match(/../g) ?? [], (byte) => parseInt(byte, 16));
}

function hex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function arrayBuffer(value: Uint8Array): ArrayBuffer {
  return value.buffer.slice(
    value.byteOffset,
    value.byteOffset + value.byteLength,
  ) as ArrayBuffer;
}

async function digest(value: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", arrayBuffer(value)));
}

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  const object = value as Record<string, unknown>;
  return `{${Object.keys(object).sort().map((key) =>
    `${JSON.stringify(key)}:${stableJson(object[key])}`
  ).join(",")}}`;
}

function readU32(data: Uint8Array, offset: number): number {
  return new DataView(data.buffer, data.byteOffset, data.byteLength).getUint32(offset, true);
}

function readU64(data: Uint8Array, offset: number): bigint {
  return new DataView(data.buffer, data.byteOffset, data.byteLength).getBigUint64(offset, true);
}

function readI64(data: Uint8Array, offset: number): bigint {
  return new DataView(data.buffer, data.byteOffset, data.byteLength).getBigInt64(offset, true);
}

function i64le(value: number): Uint8Array {
  const out = new Uint8Array(8);
  new DataView(out.buffer).setBigInt64(0, BigInt(value), true);
  return out;
}

function u64le(value: number): Uint8Array {
  const out = new Uint8Array(8);
  new DataView(out.buffer).setBigUint64(0, BigInt(value), true);
  return out;
}

async function discriminator(name: string): Promise<Uint8Array> {
  return (await digest(new TextEncoder().encode(`account:${name}`))).slice(0, 8);
}

function equal(a: Uint8Array, b: Uint8Array): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

function check(
  checks: VerificationCheck[],
  id: string,
  label: string,
  ok: boolean,
  pass: string,
  fail: string,
): void {
  checks.push({ id, label, status: ok ? "pass" : "fail", detail: ok ? pass : fail });
}

function absent(
  checks: VerificationCheck[],
  id: string,
  label: string,
  detail: string,
): void {
  checks.push({ id, label, status: "absent", detail });
}

function notApplicable(
  checks: VerificationCheck[],
  id: string,
  label: string,
  detail: string,
): void {
  checks.push({ id, label, status: "not-applicable", detail });
}

async function rpcAccount(accountAddress: Address): Promise<{ data: Uint8Array; owner: string } | null> {
  const response = await fetch(DEVNET_RPC, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "getAccountInfo",
      params: [accountAddress, { encoding: "base64", commitment: "confirmed" }],
    }),
  });
  if (!response.ok) throw new Error(`devnet RPC returned ${response.status}`);
  const body = await response.json();
  if (body.error) throw new Error(body.error.message ?? "devnet RPC error");
  const value = body.result?.value;
  if (!value) return null;
  return { data: bytesFromB64(value.data[0]), owner: value.owner };
}

interface ParsedAttestation {
  enclave: string;
  measurement: string;
  reportData: string;
  bindingVersion: number;
  registryHash: string;
  runtimeVersion: string;
  grade: string;
  receiptCount: bigint;
}

async function parseAttestation(data: Uint8Array): Promise<ParsedAttestation> {
  if (data.length < 215 || !equal(data.slice(0, 8), await discriminator("AttestationAccount"))) {
    throw new Error("invalid AttestationAccount discriminator or length");
  }
  let offset = 8;
  const enclave = hex(data.slice(offset, offset + 32)); offset += 32;
  const measurement = hex(data.slice(offset, offset + 48)); offset += 48;
  const reportData = hex(data.slice(offset, offset + 32)); offset += 32;
  offset += 32;
  const bindingVersion = data[offset]; offset += 1;
  const registryHash = hex(data.slice(offset, offset + 32)); offset += 32;
  const runtimeLength = readU32(data, offset); offset += 4;
  if (runtimeLength > 64 || offset + runtimeLength + 25 > data.length) {
    throw new Error("invalid runtime_version length");
  }
  const runtimeVersion = new TextDecoder().decode(data.slice(offset, offset + runtimeLength));
  offset += runtimeLength;
  const grade = ["snp", "launch-only", "none"][data[offset]] ?? "unknown"; offset += 1;
  offset += 8;
  const receiptCount = readU64(data, offset);
  return { enclave, measurement, reportData, bindingVersion, registryHash, runtimeVersion, grade, receiptCount };
}

interface ParsedReceipt {
  enclave: string;
  promptHash: string;
  responseHash: string;
  modelHash: string;
  timestamp: bigint;
  index: bigint;
}

async function parseReceipt(data: Uint8Array): Promise<ParsedReceipt> {
  if (data.length < 161 || !equal(data.slice(0, 8), await discriminator("ReceiptAccount"))) {
    throw new Error("invalid ReceiptAccount discriminator or length");
  }
  let offset = 8;
  const enclave = hex(data.slice(offset, offset + 32)); offset += 32;
  const promptHash = hex(data.slice(offset, offset + 32)); offset += 32;
  const responseHash = hex(data.slice(offset, offset + 32)); offset += 32;
  const modelHash = hex(data.slice(offset, offset + 32)); offset += 32;
  const timestamp = readI64(data, offset); offset += 8;
  const index = readU64(data, offset);
  return { enclave, promptHash, responseHash, modelHash, timestamp, index };
}

async function verifyAmdChain(
  report: Uint8Array,
  attestation: AttestationDoc,
  checks: VerificationCheck[],
): Promise<void> {
  const bundle = attestation.vcek_chain;
  if (!bundle) {
    absent(checks, "amd-chain", "AMD certificate chain", "attestation has no VCEK/ASK/ARK certificate bundle");
    return;
  }
  const vcekBytes = bytesFromB64(bundle.vcek_der_b64);
  const askBytes = bytesFromB64(bundle.ask_der_b64);
  const arkBytes = bytesFromB64(bundle.ark_der_b64);
  const expectedArk = (policy.amd_ark_der_sha256 as Record<string, string>)[bundle.product];
  const actualArk = hex(await digest(arkBytes));
  check(
    checks,
    "amd-ark",
    "AMD ARK trust anchor",
    Boolean(expectedArk) && actualArk === expectedArk,
    `${bundle.product} ARK matches the verifier's pinned DER digest`,
    expectedArk ? `${bundle.product} ARK digest does not match policy` : `no pinned ARK for ${bundle.product}`,
  );

  const vcek = new X509Certificate(arrayBuffer(vcekBytes));
  const ask = new X509Certificate(arrayBuffer(askBytes));
  const ark = new X509Certificate(arrayBuffer(arkBytes));
  const now = Date.now();
  const datesValid = [vcek, ask, ark].every(
    (cert) => cert.notBefore.getTime() <= now && now <= cert.notAfter.getTime(),
  );
  const namesMatch = vcek.issuer === ask.subject && ask.issuer === ark.subject && ark.issuer === ark.subject;
  const signaturesValid =
    await vcek.verify({ publicKey: ask.publicKey, signatureOnly: true }) &&
    await ask.verify({ publicKey: ark.publicKey, signatureOnly: true }) &&
    await ark.verify({ publicKey: ark.publicKey, signatureOnly: true });
  check(
    checks,
    "amd-chain",
    "VCEK → ASK → ARK",
    datesValid && namesMatch && signaturesValid,
    "certificate signatures, issuers, and validity windows verified in this browser",
    "AMD certificate chain verification failed",
  );

  const key = await vcek.publicKey.export(
    { name: "ECDSA", namedCurve: "P-384" },
    ["verify"],
  );
  const r = report.slice(0x2a0, 0x2a0 + 48).reverse();
  const s = report.slice(0x2a0 + 72, 0x2a0 + 72 + 48).reverse();
  const signatureValid = await crypto.subtle.verify(
    { name: "ECDSA", hash: "SHA-384" },
    key,
    arrayBuffer(concat(r, s)),
    arrayBuffer(report.slice(0, 0x2a0)),
  );
  check(
    checks,
    "snp-signature",
    "SNP report signature",
    signatureValid,
    "report signature verified under the AMD-issued VCEK",
    "report signature is invalid under the supplied VCEK",
  );
}

async function verifyPolicy(
  report: Uint8Array,
  attestation: AttestationDoc,
  checks: VerificationCheck[],
): Promise<void> {
  const view = new DataView(report.buffer, report.byteOffset, report.byteLength);
  const version = view.getUint32(0, true);
  const guestPolicy = view.getBigUint64(8, true);
  const vmpl = view.getUint32(0x30, true);
  const signatureAlgorithm = view.getUint32(0x34, true);
  const measurement = hex(report.slice(0x90, 0xc0));
  const tcb = report.slice(0x180, 0x188);
  const floor = policy.minimum_reported_tcb;
  const tcbOk =
    tcb[0] >= floor.fmc &&
    tcb[1] >= floor.bootloader &&
    tcb[2] >= floor.tee &&
    tcb[3] >= floor.snp &&
    tcb[7] >= floor.microcode;
  const upperReportDataZero = report.slice(0x70, 0x90).every((value) => value === 0);
  const policyOk =
    policy.allowed_report_versions.includes(version) &&
    policy.allowed_vmpl.includes(vmpl) &&
    signatureAlgorithm === 1 &&
    (!policy.require_debug_disabled || (guestPolicy & (1n << 19n)) === 0n) &&
    upperReportDataZero &&
    policy.allowed_measurements.includes(measurement) &&
    policy.allowed_builds.some((item) =>
      item.measurement === measurement &&
      item.server_build_hash === attestation.server_build_hash &&
      item.execution_mode === (attestation.execution?.mode ?? "guest-declared")
    ) &&
    tcbOk;
  check(
    checks,
    "snp-policy",
    "local SNP policy",
    policyOk,
    `exact measurement/build pair approved for ${attestation.execution?.mode ?? "guest-declared"}; VMPL ${vmpl}; debug disabled; TCB floor met`,
    "report version, VMPL, debug bit, measurement/build pair, or TCB failed bundled policy",
  );
}

async function verifyAttestationPda(
  attestation: AttestationDoc,
  enclave: Uint8Array,
  checks: VerificationCheck[],
): Promise<{ pda: string; account: ParsedAttestation | null }> {
  const [pda] = await getProgramDerivedAddress({
    programAddress: address(REGISTRY_PROGRAM),
    seeds: [new TextEncoder().encode("attestation"), enclave],
  });
  const rpc = await rpcAccount(pda);
  if (!rpc) {
    absent(checks, "attestation-pda", "attestation PDA", "no account exists for this enclave key on devnet");
    return { pda, account: null };
  }
  const account = await parseAttestation(rpc.data);
  const matches =
    rpc.owner === REGISTRY_PROGRAM &&
    account.enclave === hex(enclave) &&
    account.measurement === attestation.snp_measurement &&
    account.reportData === attestation.report_data &&
    account.bindingVersion === attestation.binding_version &&
    account.registryHash === attestation.registry_hash &&
    account.runtimeVersion === attestation.runtime_version &&
    account.grade === attestation.grade;
  check(
    checks,
    "attestation-pda",
    "attestation PDA",
    matches,
    `raw devnet account matches report, registry, runtime, grade, and enclave key`,
    "raw devnet attestation account differs from the signed document",
  );
  return { pda, account };
}

async function verifyReceipt(
  receipt: Receipt,
  attestation: AttestationDoc,
  enclave: Uint8Array,
  checks: VerificationCheck[],
): Promise<string | undefined> {
  if (
    !receipt.prompt_hash || !receipt.response_hash || !receipt.model_hash ||
    receipt.timestamp == null || !receipt.sig_b64
  ) {
    check(checks, "receipt-signature", "receipt signature", false, "", "receipt is missing signed fields");
    return;
  }
  const message = concat(
    bytesFromHex(receipt.prompt_hash),
    bytesFromHex(receipt.response_hash),
    bytesFromHex(receipt.model_hash),
    i64le(receipt.timestamp),
  );
  const signatureValid = nacl.sign.detached.verify(message, bytesFromB64(receipt.sig_b64), enclave);
  const receiptKeyMatches = typeof receipt.enclave_pubkey_b64 === "string" &&
    equal(bytesFromB64(receipt.enclave_pubkey_b64), enclave);
  const modelInRegistry = (attestation.registry ?? []).some(
    (entry) => entry.weights_sha256 === receipt.model_hash,
  );
  check(
    checks,
    "receipt-signature",
    "receipt signature",
    signatureValid && receiptKeyMatches && modelInRegistry,
    "Ed25519 signature is valid and the declared model hash is in the attested registry",
    "signature, enclave key, or declared model hash does not match the attested registry",
  );

  if (receipt.onchain_status !== "confirmed" || receipt.receipt_index == null) {
    absent(checks, "receipt-pda", "inference receipt PDA", "this response was not confirmed on devnet");
    return;
  }
  const [pda] = await getProgramDerivedAddress({
    programAddress: address(REGISTRY_PROGRAM),
    seeds: [new TextEncoder().encode("receipt"), enclave, u64le(receipt.receipt_index)],
  });
  const rpc = await rpcAccount(pda);
  if (!rpc) {
    check(checks, "receipt-pda", "inference receipt PDA", false, "", "claimed receipt account does not exist");
    return pda;
  }
  const account = await parseReceipt(rpc.data);
  const matches =
    rpc.owner === REGISTRY_PROGRAM &&
    pda === receipt.receipt_pda &&
    account.enclave === hex(enclave) &&
    account.promptHash === receipt.prompt_hash &&
    account.responseHash === receipt.response_hash &&
    account.modelHash === receipt.model_hash &&
    account.timestamp === BigInt(receipt.timestamp) &&
    account.index === BigInt(receipt.receipt_index);
  check(
    checks,
    "receipt-pda",
    "inference receipt PDA",
    matches,
    `raw devnet receipt[${receipt.receipt_index}] exactly matches the signed hashes`,
    "raw devnet receipt account differs from the signed receipt",
  );
  return pda;
}

export async function verifyReceiptContent(
  receipt: Receipt,
  model: string,
  messages: { role: string; content: string }[],
  maxTokens: number,
  response: string,
): Promise<void> {
  if (receipt.request_hash_version !== 2) {
    throw new Error("response receipt does not use request hash version 2");
  }
  if (!receipt.prompt_hash || !receipt.response_hash) {
    throw new Error("response receipt is missing content hashes");
  }
  const requestPreimage = stableJson({
    endpoint: "openai-chat-completions",
    max_tokens: maxTokens,
    messages,
    model,
    schema: "vinfer-request-v2",
  });
  const [promptHash, responseHash] = await Promise.all([
    digest(new TextEncoder().encode(requestPreimage)),
    digest(new TextEncoder().encode(response)),
  ]);
  if (hex(promptHash) !== receipt.prompt_hash) {
    throw new Error("receipt prompt hash does not match this chat request");
  }
  if (hex(responseHash) !== receipt.response_hash) {
    throw new Error("receipt response hash does not match the displayed text");
  }
}

export async function verifyInBrowser(
  attestation: AttestationDoc,
  receipt: Receipt | null,
): Promise<BrowserVerification> {
  const checks: VerificationCheck[] = [];
  try {
    if (attestation.grade !== "snp" || !attestation.snp_report_b64) {
      check(checks, "snp-grade", "SNP report", false, "", "server did not provide an SNP-grade report");
      return { status: "failed", attestationTrusted: false, checks };
    }
    if (
      !attestation.enclave_pubkey_b64 || !attestation.registry_hash ||
      !attestation.server_build_hash || !attestation.report_data
    ) {
      throw new Error("attestation document is missing binding fields");
    }
    const enclave = bytesFromB64(attestation.enclave_pubkey_b64);
    const report = bytesFromB64(attestation.snp_report_b64);
    if (enclave.length !== 32 || report.length < 0x2a0 + 120) {
      throw new Error("attestation key or report has an invalid length");
    }

    const expectedBinding = hex(await digest(concat(
      enclave,
      bytesFromHex(attestation.registry_hash),
      bytesFromHex(attestation.server_build_hash),
    )));
    const reportDataMatches =
      expectedBinding === attestation.report_data &&
      hex(report.slice(0x50, 0x70)) === attestation.report_data;
    check(
      checks,
      "binding-v2",
      "REPORT_DATA binding v2",
      attestation.binding_version === 2 && reportDataMatches,
      "enclave key, registry hash, and build hash match the signed report",
      "document binding or signed REPORT_DATA differs",
    );

    const registryPayload = [...(attestation.registry ?? [])]
      .sort((a, b) => a.id.localeCompare(b.id))
      .map((entry) => `${entry.id} ${entry.weights_sha256}`)
      .join("\n");
    const registryDigest = hex(await digest(new TextEncoder().encode(registryPayload)));
    check(
      checks,
      "registry-digest",
      "model registry digest",
      registryDigest === attestation.registry_hash,
      "served model IDs and declared hashes reproduce registry_hash",
      "served registry entries do not reproduce registry_hash",
    );

    const executionMode = attestation.execution?.mode ?? "guest-declared";
    if (executionMode === "snp-measured-dm-verity") {
      const manifest = attestation.execution?.manifest;
      const manifestDigest = manifest
        ? hex(await digest(new TextEncoder().encode(stableJson(manifest))))
        : "";
      check(
        checks,
        "execution-manifest",
        "execution manifest digest",
        Boolean(manifest) &&
          manifestDigest === attestation.server_build_hash &&
          manifest?.registry_hash === attestation.registry_hash &&
          manifest?.runtime_version === attestation.runtime_version,
        "canonical measured-boot/dm-verity manifest matches build and registry",
        "execution manifest does not match build, registry, or runtime",
      );
    } else {
      const runtimeDigest = attestation.runtime_version
        ? hex(await digest(new TextEncoder().encode(attestation.runtime_version)))
        : "";
      check(
        checks,
        "runtime-digest",
        "runtime version digest",
        runtimeDigest === attestation.server_build_hash,
        "runtime_version reproduces the guest-declared build hash",
        "runtime_version does not reproduce server_build_hash",
      );
    }

    if (attestation.hpke_public_key_b64 && attestation.hpke_binding_signature_b64) {
      const hpke = bytesFromB64(attestation.hpke_public_key_b64);
      const signature = bytesFromB64(attestation.hpke_binding_signature_b64);
      const hpkeValid = hpke.length === 32 && signature.length === 64 &&
        nacl.sign.detached.verify(concat(HPKE_DOMAIN, hpke), signature, enclave);
      check(
        checks,
        "hpke-binding",
        "HPKE key binding",
        hpkeValid,
        "enclave Ed25519 key signed the ephemeral HPKE key",
        "HPKE key signature is invalid",
      );
    } else if (attestation.component === "claude-attested-proxy") {
      notApplicable(
        checks,
        "hpke-binding",
        "HPKE key binding",
        "not used by the TLS-only Claude proxy; Anthropic receives plaintext",
      );
    } else {
      absent(checks, "hpke-binding", "HPKE key binding", "attestation has no HPKE key binding");
    }

    await verifyAmdChain(report, attestation, checks);
    await verifyPolicy(report, attestation, checks);
    const pda = await verifyAttestationPda(attestation, enclave, checks);
    const attestationTrusted = checks.every((item) => item.status === "pass");
    const receiptPda = receipt
      ? await verifyReceipt(receipt, attestation, enclave, checks)
      : undefined;
    if (!receipt) {
      absent(checks, "receipt-signature", "receipt signature", "no response receipt yet");
      absent(checks, "receipt-pda", "inference receipt PDA", "no response receipt yet");
    }
    const status = checks.some((item) => item.status === "fail")
      ? "failed"
      : checks.some((item) => item.status === "absent")
        ? "incomplete"
        : "verified";
    return {
      status,
      attestationTrusted,
      checks,
      attestationPda: pda.pda,
      receiptPda,
    };
  } catch (error) {
    checks.push({
      id: "verifier-error",
      label: "browser verifier",
      status: "fail",
      detail: error instanceof Error ? error.message : String(error),
    });
    return { status: "failed", attestationTrusted: false, checks };
  }
}
