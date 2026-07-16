---
name: inference
title: "Verified Inference"
description: "Attested LLM inference on bare-metal AMD EPYC SEV TEE. Pay-per-token via x402 session channels; every paid response returns an on-chain receipt and attestation grade. OpenAI-compatible chat for BitNet, Llama-3.1-8B, Llama-3.3-70B, GLM-5.2."
use_case: "Use when you need LLM chat completions with a cryptographic, on-chain-verifiable receipt binding the exact model and I/O hashes to a hardware-attested enclave — proof of which model produced a response, not just the response."
category: ai_ml
service_url: https://verified-inference.solana.org
openapi:
  url: https://verified-inference.solana.org/openapi.json
---

OpenAI-compatible chat completions where **every paid response carries an on-chain receipt ID and an attestation grade** — attested inference, not just inference. Runs on bare-metal AMD EPYC Turin under AMD SEV memory encryption; the attestation binds the enclave signing key and the exact served model set (registry hash).

## Payment

x402 USDC on Solana via the **session intent** ([draft-solana-session-00](https://paymentauth.org/draft-solana-session-00.html)): open a channel once (on-chain escrow), then sign cumulative-amount vouchers off-chain and pay per token. Billed on actual streamed tokens; the upfront quote is reconciled and the unused portion refunded to channel balance. Two on-chain transactions per session (open, close).

Prices are derived from measured throughput on the host and charged per token:

| model | quant | price |
|---|---|---|
| `bitnet-2b` | i2_s | $3.0636/1M in · $12.2544/1M out |
| `8b-q4` | Q4_K_M | $4.8166/1M in · $19.2665/1M out |
| `8b-q8` | Q8_0 | $6.0296/1M in · $24.1183/1M out |
| `70b-q4` | Q4_K_M | $24.0689/1M in · $96.2757/1M out |
| `glm-5.2-q4` | UD-Q4_K_XL | $21.9698/1M in · $87.8792/1M out |

## Endpoints

- `POST /v1/chat/completions` — paid (x402 session). OpenAI-shaped; the `x_vinfer` field carries live metrics, the signed receipt, and settlement.
- `POST /v1/infer_sealed` — paid. HPKE-encrypted prompt (encrypt-to-enclave); the operator on the TLS path never sees plaintext.
- `GET /v1/models` — free. Models, measured stats, prices, attestation status.
- `GET /v1/attestation` — free. Enclave key, binding version, registry hash, HPKE public key.
- `GET /v1/receipts/{id}` — free. Fetch a signed receipt.

Verify any receipt end to end (attestation → AMD KDS chain → enclave key → registry PDA → receipt signature → on-chain record) with the `vinfer verify` CLI.
