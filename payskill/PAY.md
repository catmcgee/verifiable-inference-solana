---
category: ai_ml
description: OpenAI-compatible CPU inference with AMD SEV-SNP attestation, live performance
  metrics, and signed hash-only receipts.
endpoints:
- description: List attested model registry entries and prices.
  method: GET
  path: v1/models
- description: Fetch the current AMD SEV-SNP attestation document.
  method: GET
  path: v1/attestation
- description: Fetch a signed hash-only inference receipt.
  method: GET
  path: v1/receipts/{receipt_id}
- description: Generate a non-streaming OpenAI-compatible completion (stream=false)
    with live metrics and an SNP-key-signed receipt.
  method: POST
  path: v1/chat/completions
  pricing:
    dimensions:
    - direction: input
      meter:
        path: /usage/prompt_tokens
        source: response_json
      scale: 1000000
      tiers:
      - price_usd: 26.4626
      unit: tokens
    - direction: output
      meter:
        path: /usage/completion_tokens
        source: response_json
      scale: 1000000
      tiers:
      - price_usd: 105.8504
      unit: tokens
  resource: chat-completions
name: inference
service_url: https://pay.example.invalid
title: Verified Inference
version: v1
use_case: Use for paid OpenAI-compatible CPU inference when live performance metrics
  and an AMD SEV-SNP-bound signed receipt are required.
---

> **DEVELOPMENT ARTIFACT. DO NOT PUBLISH UNTIL MAINNET AND LIVE PROBES PASS.**

OpenAI-compatible chat completion on the measured AMD CPU service. Successful
responses include live latency/throughput metrics, an SNP-key-signed hash-only
receipt ID, and the server-reported attestation grade.

The x402 gateway authorizes a per-request ceiling, forwards only after payment
verification, reads the final OpenAI usage object, settles measured input and
output token cost, and refunds the unused ceiling. Calls that do not return
valid usage fail settlement rather than guessing a charge.

Paid calls currently require `stream: false`: settlement meters the final JSON
`usage` object. The separately authenticated browser console supports SSE.

| model | USDC / 1M input tokens | USDC / 1M output tokens |
|---|---:|---:|
| `bitnet-2b` | $3.3407 | $13.3629 |
| `8b-q4` | $5.0962 | $20.3847 |
| `8b-q8` | $6.3269 | $25.3074 |
| `70b-q4` | $26.4626 | $105.85 |
| `glm-5.2-q4` | $21.9698 | $87.8792 |

The frontmatter's endpoint price is the conservative unknown-model fallback.
The live x402 challenge and settlement use the matching model variant above.

The SNP report binds the guest signing key, complete hash-bearing registry
digest, and build identifier. Runtime availability is reported separately.
The current mutable guest root means this does not independently
prove which Python code or model weights executed. Leg C is not exposed here.
Leg D verification remains a stub and is not offered as a paid endpoint.

Use `vinfer verify <receipt.json>` for the SNP/KDS, key-binding, registry, and
signature checks. Exact inference-receipt PDA verification is available only
for receipts whose `onchain_status` is `confirmed`; current paid responses say
`not-posted`. Anthropic is not called by this route.
