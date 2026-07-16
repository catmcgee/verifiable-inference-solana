"""pay-skills listing generator (ADDON step 5) — GENERATED, never hand-written.

Emits a pay-skills provider PAY.md (validated shape: name/title/description≤255/
use_case/category/service_url/openapi.url) + the OpenAPI doc from the FastAPI
app. Validated with the pay `create_skill` tool; passes structurally. Publish is
P5-gated: deploy the API at an https host, point service_url + openapi.url at it,
then `pay skills probe` + PR to solana-foundation/pay-skills.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "payskill" / "generated"


def emit_openapi() -> None:
    import os
    os.environ.setdefault("VINFER_X402", "1")
    from server.main import app
    spec = app.openapi()
    spec["info"]["title"] = "verified-inference"
    keep = {"/v1/chat/completions", "/v1/models", "/v1/attestation",
            "/v1/receipts/{receipt_id}", "/v1/infer_sealed"}
    spec["paths"] = {k: v for k, v in spec["paths"].items() if k in keep}
    (OUT / "openapi.json").write_text(json.dumps(spec, indent=2))


def emit_paymd(host: str, operator: str) -> None:
    entries = [e for e in yaml.safe_load((ROOT / "models.yaml").read_text())
               if e.get("weights_sha256") and e.get("price_per_1m_out_usdc")]
    if not entries:
        sys.exit("nothing listable: no model has weights + generated prices")
    rows = "\n".join(
        f"| `{e['id']}` | {e['quant']} | ${e['price_per_1m_in_usdc']}/1M in · "
        f"${e['price_per_1m_out_usdc']}/1M out |" for e in entries)
    md = f"""---
name: inference
title: "Verified Inference"
description: "Attested LLM inference on bare-metal AMD EPYC SEV TEE. Pay-per-token via x402 session channels; every paid response returns an on-chain receipt and attestation grade. OpenAI-compatible chat for BitNet, Llama-3.1-8B, Llama-3.3-70B, GLM-5.2."
use_case: "Use when you need LLM chat completions with a cryptographic, on-chain-verifiable receipt binding the exact model and I/O hashes to a hardware-attested enclave — proof of which model produced a response, not just the response."
category: ai_ml
service_url: {host}
openapi:
  url: {host}/openapi.json
---

OpenAI-compatible chat completions where **every paid response carries an on-chain receipt ID and an attestation grade** — attested inference, not just inference. Runs on bare-metal AMD EPYC Turin under AMD SEV memory encryption; the attestation binds the enclave signing key and the exact served model set (registry hash).

## Payment

x402 USDC on Solana via the **session intent** ([draft-solana-session-00](https://paymentauth.org/draft-solana-session-00.html)): open a channel once (on-chain escrow), then sign cumulative-amount vouchers off-chain and pay per token. Billed on actual streamed tokens; the upfront quote is reconciled and the unused portion refunded to channel balance. Two on-chain transactions per session (open, close).

Prices are derived from measured throughput on the host and charged per token:

| model | quant | price |
|---|---|---|
{rows}

## Endpoints

- `POST /v1/chat/completions` — paid (x402 session). OpenAI-shaped; the `x_vinfer` field carries live metrics, the signed receipt, and settlement.
- `POST /v1/infer_sealed` — paid. HPKE-encrypted prompt (encrypt-to-enclave); the operator on the TLS path never sees plaintext.
- `GET /v1/models` — free. Models, measured stats, prices, attestation status.
- `GET /v1/attestation` — free. Enclave key, binding version, registry hash, HPKE public key.
- `GET /v1/receipts/{{id}}` — free. Fetch a signed receipt.

Verify any receipt end to end (attestation → AMD KDS chain → enclave key → registry PDA → receipt signature → on-chain record) with the `vinfer verify` CLI.
"""
    (OUT / "PAY.md").write_text(md)
    print(f"wrote {OUT}/PAY.md ({len(entries)} models) + openapi.json")
    print("P5: deploy at an https host, set host, then `pay skills probe` + PR "
          "to providers/" + operator + "/inference/")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    host = sys.argv[1] if len(sys.argv) > 1 else "https://REPLACE_WITH_DEPLOYED_HOST"
    operator = sys.argv[2] if len(sys.argv) > 2 else "solana-foundation"
    emit_openapi()
    emit_paymd(host, operator)
