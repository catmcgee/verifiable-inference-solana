// API client for the verified-inference server.
// Canonical surface (fixed): POST /v1/chat/completions · GET /v1/models ·
// GET /v1/attestation · GET /v1/receipts/{id}.
//
// Browser requests go same-origin to /vinfer/* — next.config.ts rewrites them
// to NEXT_PUBLIC_VINFER_URL, so the FastAPI server needs no CORS config.

import { createSealedSession, type SealedPayload } from "@/lib/e2e";

export const SERVER =
  process.env.NEXT_PUBLIC_VINFER_URL ?? "http://127.0.0.1:8477";

const BASE = "/vinfer";
export type LiveLeg = "A" | "B" | "C";

function baseForLeg(leg: LiveLeg): string {
  if (leg === "A") return "/vinfer-a";
  if (leg === "C") return "/vinfer-c";
  return BASE;
}

export interface ModelInfo {
  id: string;
  quant: string | null;
  runtime: string | null;
  legs: string[];
  ctx_max?: number | null;
  backend?: string | null;
  status: string;
  weights_sha256?: string | null;
  price_per_1m_in_usdc: number | null;
  price_per_1m_out_usdc: number | null;
}

export interface AttestationDoc {
  component?: string | null;
  grade: string; // none | launch-only | snp
  binding_version: number;
  sev_mode?: string | null;
  enclave_pubkey_b64?: string | null;
  report_data?: string | null;
  registry_hash?: string | null;
  server_build_hash?: string | null;
  snp_measurement?: string | null;
  snp_report_b64?: string | null;
  hpke_public_key_b64?: string | null;
  hpke_binding_signature_b64?: string | null;
  runtime_version?: string | null;
  execution?: {
    mode?: string | null;
    manifest?: Record<string, unknown> | null;
  } | null;
  registry?: { id: string; weights_sha256: string }[];
  vcek_chain?: {
    product: string;
    vcek_der_b64: string;
    ask_der_b64: string;
    ark_der_b64: string;
  } | null;
  note?: string | null;
}

export interface Metrics {
  ttft_ms?: number | null;
  itl_ms_p50?: number | null;
  itl_ms_p99?: number | null;
  tokens_per_s?: number | null;
  e2e_ms?: number | null;
  output_tokens?: number | null;
  sev_mode?: string | null;
  backend?: string | null;
  receipt_sign_ms?: number | null;
  [key: string]: unknown;
}

export interface Receipt {
  receipt_id?: string;
  enclave_pubkey_b64?: string;
  prompt_hash?: string;
  response_hash?: string;
  model_hash?: string;
  timestamp?: number;
  sig_b64?: string;
  attestation_pda?: string;
  onchain_status?: "not-posted" | "submitted" | "confirmed" | string;
  receipt_index?: number;
  receipt_pda?: string;
  receipt_tx?: string;
  [key: string]: unknown;
}

interface Usage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
}

export interface ChatResponse {
  id: string;
  model: string;
  choices: { index: number; finish_reason: string; message: { role: string; content: string } }[];
  usage?: Usage;
  x_vinfer?: {
    metrics?: Metrics;
    receipt?: Receipt;
    registry_hash?: string;
    attestation_grade?: string;
  };
}

interface SealedChatResponse {
  model: string;
  resp_nonce: string;
  sealed_response: string;
  sealed_metrics: SealedPayload;
  sealed_usage: SealedPayload;
  receipt: Receipt;
}

interface ChatStreamChunk {
  id: string;
  model: string;
  choices?: {
    delta?: { content?: unknown };
    finish_reason?: unknown;
  }[];
  usage?: Usage;
  x_vinfer?: ChatResponse["x_vinfer"];
}

export interface AuthSession {
  required: boolean;
  authenticated: boolean;
  mode?: "open" | "browser-session" | "gateway" | null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  leg: LiveLeg = "B",
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${baseForLeg(leg)}${path}`, {
      credentials: "same-origin",
      ...init,
    });
  } catch {
    throw new Error(`no route to server (${SERVER})`);
  }
  if (!res.ok) throw await responseError(res);
  return res.json() as Promise<T>;
}

async function responseError(res: Response): Promise<ApiError> {
  let detail = `${res.status}`;
  try {
    const body = await res.json();
    if (body?.detail) detail = `${res.status} — ${body.detail}`;
    else if (body?.error) detail = `${res.status} — ${body.error}`;
    else if (res.status === 402 && body?.accepts?.[0]) {
      const offer = body.accepts[0];
      detail = `402 — ${offer.scheme} payment required on ${offer.network}; inspect with the vinfer CLI`;
    }
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(detail, res.status);
}

async function* readSse<T>(res: Response, missingBodyMessage: string): AsyncGenerator<T> {
  if (!res.body) throw new Error(missingBodyMessage);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const event of events) {
      const data = event
        .split("\n")
        .find((line) => line.startsWith("data: "))
        ?.slice(6);
      if (data && data !== "[DONE]") yield JSON.parse(data) as T;
    }
    if (done) return;
  }
}

export async function getModels(leg: LiveLeg = "B"): Promise<ModelInfo[]> {
  const body = await request<{ data: ModelInfo[] }>("/v1/models", undefined, leg);
  return body.data ?? [];
}

export function getAttestation(leg: LiveLeg = "B"): Promise<AttestationDoc> {
  return request<AttestationDoc>("/v1/attestation", undefined, leg);
}

export function getAuthSession(leg: LiveLeg = "B"): Promise<AuthSession> {
  return request<AuthSession>("/v1/auth/session", { cache: "no-store" }, leg);
}

export function createAuthSession(accessCode: string, leg: LiveLeg = "B"): Promise<AuthSession> {
  return request<AuthSession>("/v1/auth/session", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ access_code: accessCode }),
  }, leg);
}

export function deleteAuthSession(leg: LiveLeg = "B"): Promise<AuthSession> {
  return request<AuthSession>("/v1/auth/session", { method: "DELETE" }, leg);
}

export async function postChatStream(
  leg: LiveLeg,
  model: string,
  messages: { role: string; content: string }[],
  max_tokens: number,
  onDelta: (text: string) => void,
): Promise<ChatResponse> {
  let res: Response;
  try {
    res = await fetch(`${baseForLeg(leg)}/v1/chat/completions`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ model, messages, max_tokens, stream: true }),
    });
  } catch {
    throw new Error(`no route to server (${SERVER})`);
  }
  if (!res.ok) throw await responseError(res);
  let final: ChatResponse | null = null;
  let content = "";
  let finishReason = "stop";
  for await (const chunk of readSse<ChatStreamChunk>(
    res,
    "streaming response has no body",
  )) {
    const delta = chunk.choices?.[0]?.delta?.content;
    if (typeof delta === "string") {
      content += delta;
      onDelta(delta);
    }
    if (typeof chunk.choices?.[0]?.finish_reason === "string") {
      finishReason = chunk.choices[0].finish_reason;
    }
    if (chunk.x_vinfer) {
      final = {
        id: chunk.id,
        model: chunk.model,
        choices: [],
        usage: chunk.usage,
        x_vinfer: chunk.x_vinfer,
      };
    }
  }
  if (!final) throw new Error("stream ended without final metrics and receipt");
  final.choices = [{
    index: 0,
    finish_reason: finishReason,
    message: { role: "assistant", content },
  }];
  return final;
}

export async function postChatE2E(
  model: string,
  messages: { role: string; content: string }[],
  maxTokens: number,
  attestation: AttestationDoc,
  onDelta: (text: string) => void,
): Promise<ChatResponse> {
  if (!attestation.hpke_public_key_b64) {
    throw new Error("verified attestation has no HPKE public key");
  }
  const plaintext = new TextEncoder().encode(JSON.stringify({
    schema: "vinfer-e2e-chat-v1",
    messages,
  }));
  const session = await createSealedSession(
    attestation.hpke_public_key_b64,
    plaintext,
  );

  let res: Response;
  try {
    res = await fetch(`${baseForLeg("B")}/v1/chat_e2e`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        model,
        max_tokens: maxTokens,
        stream: true,
        enc: session.enc,
        ciphertext: session.ciphertext,
      }),
    });
  } catch {
    throw new Error(`no route to server (${SERVER})`);
  }
  if (!res.ok) throw await responseError(res);
  const decoder = new TextDecoder();
  let body: SealedChatResponse | null = null;
  for await (const chunk of readSse<SealedChatResponse & {
    sealed_delta?: SealedPayload;
  }>(res, "sealed streaming response has no body")) {
    if (chunk.sealed_delta) {
      onDelta(decoder.decode(await session.open(chunk.sealed_delta)));
    } else if (chunk.receipt) {
      body = chunk;
    }
  }
  if (!body) throw new Error("sealed stream ended without a receipt");
  const [contentBytes, metricsBytes, usageBytes] = await Promise.all([
    session.open(body),
    session.open(body.sealed_metrics),
    session.open(body.sealed_usage),
  ]);
  const content = decoder.decode(contentBytes);
  const metrics = JSON.parse(decoder.decode(metricsBytes)) as Metrics;
  const usage = JSON.parse(decoder.decode(usageBytes)) as Usage;

  return {
    id: `chatcmpl-e2e-${body.receipt.receipt_id ?? "sealed"}`,
    model: body.model,
    choices: [{
      index: 0,
      finish_reason: "stop",
      message: { role: "assistant", content },
    }],
    usage,
    x_vinfer: {
      metrics,
      receipt: body.receipt,
      registry_hash: body.receipt.attestation &&
        typeof body.receipt.attestation === "object" &&
        "registry_hash" in body.receipt.attestation
          ? String(body.receipt.attestation.registry_hash)
          : undefined,
      attestation_grade: body.receipt.attestation &&
        typeof body.receipt.attestation === "object" &&
        "grade" in body.receipt.attestation
          ? String(body.receipt.attestation.grade)
          : undefined,
    },
  };
}
