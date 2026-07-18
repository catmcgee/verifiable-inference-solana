"""Generate the pay gateway runtime spec from models.yaml.

This is the only payment-pricing projection. Rates are copied from the model
registry; the gateway observes the OpenAI-compatible response usage and settles
the x402-upto channel from those measured token counts.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from server import registry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "payskill" / "inference.yaml"


def _dimension(direction: str, price: float, usage_pointer: str) -> dict:
    return {
        "direction": direction,
        "unit": "tokens",
        "scale": 1_000_000,
        "tiers": [{"price_usd": price}],
        "meter": {"source": "response_json", "path": usage_pointer},
    }


def runtime_spec(
    *,
    upstream: str,
    network: str,
    max_request_usd: float,
) -> dict:
    models = registry.load()
    priced = [
        model
        for model in models.values()
        if model.servable
        and model.price_per_1m_in_usdc is not None
        and model.price_per_1m_out_usdc is not None
    ]
    if not priced:
        raise ValueError("models.yaml has no servable model with generated prices")
    if network not in {"localnet", "devnet", "mainnet"}:
        raise ValueError("network must be localnet, devnet, or mainnet")
    if max_request_usd <= 0:
        raise ValueError("max_request_usd must be positive")

    variants = []
    for model in priced:
        variants.append(
            {
                "param": "model",
                "value": model.id,
                "description": f"{model.id} measured registry pricing",
                "dimensions": [
                    _dimension(
                        "input", model.price_per_1m_in_usdc, "/usage/prompt_tokens"
                    ),
                    _dimension(
                        "output",
                        model.price_per_1m_out_usdc,
                        "/usage/completion_tokens",
                    ),
                ],
            }
        )

    # Top-level dimensions are a fail-closed pricing fallback for clients that
    # omit or misspell the body model. Use the highest rates in the registry;
    # the origin still rejects unknown models before inference.
    fallback_in = max(model.price_per_1m_in_usdc for model in priced)
    fallback_out = max(model.price_per_1m_out_usdc for model in priced)
    return {
        "name": "verified-inference",
        "subdomain": "verified-inference",
        "title": "Verified Inference",
        "description": (
            "OpenAI-compatible CPU inference with AMD SEV-SNP attestation, "
            "live performance metrics, and signed hash-only receipts."
        ),
        "category": "ai_ml",
        "version": "v1",
        "routing": {
            "type": "proxy",
            "url": upstream.rstrip("/") + "/",
            "auth": {
                "method": "header",
                "key": "Authorization",
                "prefix": "Bearer ",
                "value_from_env": "VINFER_ORIGIN_TOKEN",
            },
        },
        "operator": {
            "currencies": {"usd": ["USDC"]},
            "network": network,
            "fee_payer": True,
        },
        "endpoints": [
            {
                "method": "GET",
                "path": "v1/models",
                "description": "List attested model registry entries and prices.",
            },
            {
                "method": "GET",
                "path": "v1/attestation",
                "description": "Fetch the current AMD SEV-SNP attestation document.",
            },
            {
                "method": "GET",
                "path": "v1/receipts/{receipt_id}",
                "description": "Fetch a signed hash-only inference receipt.",
            },
            {
                "method": "POST",
                "path": "v1/chat/completions",
                "resource": "chat-completions",
                "description": (
                    "Generate a non-streaming OpenAI-compatible completion "
                    "(stream=false) with live metrics and an SNP-key-signed receipt."
                ),
                "metering": {
                    "schemes": ["x402-upto"],
                    "dimensions": [
                        _dimension("input", fallback_in, "/usage/prompt_tokens"),
                        _dimension("output", fallback_out, "/usage/completion_tokens"),
                    ],
                    "variants": variants,
                    "upto": {
                        "max_usd": max_request_usd,
                        "missing_usage": "error",
                    },
                },
            },
        ],
        "notes": (
            "Every successful paid completion includes an inference receipt ID "
            "and the server-reported attestation grade. x402 authorizes a ceiling; "
            "the gateway settles observed token usage and refunds the remainder."
        ),
    }


def write_runtime(
    output: Path,
    *,
    upstream: str,
    network: str,
    max_request_usd: float,
) -> None:
    spec = runtime_spec(
        upstream=upstream,
        network=network,
        max_request_usd=max_request_usd,
    )
    header = (
        "# GENERATED from models.yaml by payskill/generate_runtime.py.\n"
        "# Do not edit prices here. Regenerate after report/pricing.py.\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(header + yaml.safe_dump(spec, sort_keys=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--upstream", default="http://127.0.0.1:8477", help="authenticated origin URL"
    )
    parser.add_argument(
        "--network", choices=("localnet", "devnet", "mainnet"), default="localnet"
    )
    parser.add_argument("--max-request-usd", type=float, default=0.50)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    write_runtime(
        args.output,
        upstream=args.upstream,
        network=args.network,
        max_request_usd=args.max_request_usd,
    )
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
