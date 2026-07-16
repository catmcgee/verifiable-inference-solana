"""payskill listing generator (ADDON step 5) — GENERATED, never hand-written.

Reads models.yaml -> emits providers/<operator>/verified-inference.md plus the
`pay server start` runtime YAML. P5 gate: run ONLY after the public API is
deployed; then `pay skills provider sync` + validate via the pay-skills
validator (create_skill) before any PR. Ops note (LEDGER): verify the pay
CLI/MCP works BEFORE P5.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main(base_url: str, operator: str = "catmcgee") -> None:
    entries = [e for e in yaml.safe_load((ROOT / "models.yaml").read_text())
               if e.get("weights_sha256") and e.get("price_per_1m_out_usdc")]
    if not entries:
        sys.exit("nothing listable: no model has both weights_sha256 and generated prices")

    out_dir = ROOT / "payskill" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)

    runtime = {
        "name": "verified-inference",
        "base_url": base_url,
        "endpoints": [
            {"path": "/v1/chat/completions", "method": "POST", "x402": True},
            {"path": "/v1/models", "method": "GET", "x402": False},
            {"path": "/v1/attestation", "method": "GET", "x402": False},
            {"path": "/v1/receipts/{id}", "method": "GET", "x402": False},
        ],
        "models": [
            {"id": e["id"], "price_per_1m_in_usdc": e["price_per_1m_in_usdc"],
             "price_per_1m_out_usdc": e["price_per_1m_out_usdc"]}
            for e in entries
        ],
    }
    (out_dir / "pay-server.yaml").write_text(yaml.dump(runtime, sort_keys=False))

    rows = "\n".join(
        f"| `{e['id']}` | {e['quant']} | ${e['price_per_1m_in_usdc']}/1M in | ${e['price_per_1m_out_usdc']}/1M out |"
        for e in entries
    )
    listing = f"""# verified-inference

OpenAI-compatible chat completions where **every paid response includes an
on-chain receipt ID and an attestation grade** — attested inference, not just
inference. Runs on bare-metal AMD EPYC (SEV family TEE); attestation binds the
enclave key and the exact model set served (binding v2, registry hash).

Base URL: `{base_url}` · Payment: x402 (USDC), quoted per request as
`prompt_tokens x in_price + max_tokens x out_price`, settled upfront
(v1 limitation: no metered refund for early stop).

| model | quant | input | output |
|---|---|---|---|
{rows}

Free endpoints: `GET /v1/models`, `GET /v1/attestation`, `GET /v1/receipts/{{id}}`.
Verify any receipt: attestation -> AMD KDS chain -> enclave key -> registry PDA
-> receipt signature -> on-chain record (`vinfer verify`).
"""
    (out_dir / f"{operator}--verified-inference.md").write_text(listing)
    print(f"generated {out_dir}/pay-server.yaml and listing for {len(entries)} models")
    print("P5 next steps: pay server start → pay skills provider sync → validator → PR")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "https://PENDING.deploy")
