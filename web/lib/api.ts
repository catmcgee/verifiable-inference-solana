// API client for the verified-inference server.
// Canonical surface (fixed): POST /v1/chat/completions · GET /v1/models ·
// GET /v1/attestation · GET /v1/receipts/{id}.
//
// Browser requests go same-origin to /vinfer/* — next.config.ts rewrites them
// to NEXT_PUBLIC_VINFER_URL, so the FastAPI server needs no CORS config.

export const SERVER =
  process.env.NEXT_PUBLIC_VINFER_URL ?? "http://127.0.0.1:8477";

const BASE = "/vinfer";

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
  grade: string; // none | launch-only | snp
  binding_version: number;
  sev_mode?: string | null;
  enclave_pubkey_b64?: string | null;
  report_data?: string | null;
  registry_hash?: string | null;
  server_build_hash?: string | null;
  snp_measurement?: string | null;
  snp_report_b64?: string | null;
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
  attestation_pda?: string; // not emitted by the P2 server; used if present
  [key: string]: unknown;
}

export interface Usage {
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
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new Error(`no route to server (${SERVER})`);
  }
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = `${res.status} — ${body.detail}`;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function getModels(): Promise<ModelInfo[]> {
  const body = await request<{ data: ModelInfo[] }>("/v1/models");
  return body.data ?? [];
}

export function getAttestation(): Promise<AttestationDoc> {
  return request<AttestationDoc>("/v1/attestation");
}

export function postChat(
  model: string,
  messages: { role: string; content: string }[],
  max_tokens: number,
): Promise<ChatResponse> {
  return request<ChatResponse>("/v1/chat/completions", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ model, messages, max_tokens }),
  });
}
