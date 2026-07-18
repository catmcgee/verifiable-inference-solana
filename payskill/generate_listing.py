"""Build pay.sh provider artifacts from the generated pay runtime YAML.

Pipeline: models.yaml -> inference.yaml -> `pay skills provider sync` -> PAY.md
-> `pay catalog check`. This command never publishes or opens a pull request.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import yaml

from payskill.generate_runtime import write_runtime
from server import registry


ROOT = Path(__file__).resolve().parents[1]
PAY_ROOT = ROOT / "payskill"
GENERATED = PAY_ROOT / "generated"


def emit_openapi(output: Path, service_url: str) -> None:
    from server.main import app

    spec = app.openapi()
    spec["info"]["title"] = "Verified Inference"
    spec["servers"] = [{"url": service_url.rstrip("/")}]
    keep = {
        "/v1/chat/completions",
        "/v1/models",
        "/v1/attestation",
        "/v1/receipts/{receipt_id}",
    }
    spec["paths"] = {
        path: value for path, value in spec["paths"].items() if path in keep
    }
    chat_responses = spec["paths"]["/v1/chat/completions"]["post"]["responses"]
    chat_responses["402"] = {
        "description": "x402 payment required; see the PAYMENT-REQUIRED header."
    }
    output.write_text(json.dumps(spec, indent=2) + "\n")


def verify_live_registry(origin_url: str) -> None:
    try:
        response = httpx.get(f"{origin_url.rstrip('/')}/v1/models", timeout=20)
        response.raise_for_status()
        rows = response.json()["data"]
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"cannot verify deployed registry: {exc}")

    live = {row["id"]: row for row in rows if row.get("status") == "available"}
    expected = {
        model.id: model
        for model in registry.load().values()
        if model.servable
        and model.price_per_1m_in_usdc is not None
        and model.price_per_1m_out_usdc is not None
    }
    unavailable = sorted(set(expected) - set(live))
    if unavailable:
        sys.exit(
            f"refusing provider listing; deployed runtimes unavailable: {unavailable}"
        )
    for model_id, model in expected.items():
        row = live[model_id]
        comparisons = {
            "weights_sha256": model.weights_sha256,
            "price_per_1m_in_usdc": model.price_per_1m_in_usdc,
            "price_per_1m_out_usdc": model.price_per_1m_out_usdc,
        }
        for field, expected_value in comparisons.items():
            if row.get(field) != expected_value:
                sys.exit(
                    f"refusing stale listing: deployed {model_id} {field} "
                    f"differs from models.yaml"
                )


def _frontmatter(document: str) -> tuple[dict, str]:
    if not document.startswith("---\n"):
        raise ValueError("pay sync output has no YAML frontmatter")
    raw, separator, body = document[4:].partition("\n---\n")
    if not separator:
        raise ValueError("pay sync output has unterminated YAML frontmatter")
    return yaml.safe_load(raw), body


def _provider_body() -> str:
    rows = []
    for model in registry.load().values():
        if (
            model.servable
            and model.price_per_1m_in_usdc is not None
            and model.price_per_1m_out_usdc is not None
        ):
            rows.append(
                f"| `{model.id}` | ${model.price_per_1m_in_usdc:g} | "
                f"${model.price_per_1m_out_usdc:g} |"
            )
    prices = "\n".join(rows)
    return f"""
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
{prices}

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
""".lstrip()


def build_provider(
    *,
    origin_url: str,
    service_url: str,
    operator: str,
    network: str,
    max_request_usd: float,
    live_check: bool,
    probe: bool,
) -> Path:
    if shutil.which("pay") is None:
        sys.exit("pay CLI is required (brew install pay or npm install -g @solana/pay)")
    if live_check:
        verify_live_registry(origin_url)

    # This directory is ignored and wholly owned by this generator. Starting
    # clean prevents superseded provider-sync layouts from looking current.
    if GENERATED.exists():
        shutil.rmtree(GENERATED)
    runtime_dir = GENERATED / "runtime"
    runtime_path = runtime_dir / "inference.yaml"
    write_runtime(
        runtime_path,
        upstream=origin_url,
        network=network,
        max_request_usd=max_request_usd,
    )

    synced_root = GENERATED / "synced"
    subprocess.run(
        [
            "pay",
            "skills",
            "provider",
            "sync",
            "--operator",
            operator,
            "--origin",
            "verified-inference",
            "--out",
            str(synced_root),
            "--service-url",
            service_url,
            str(runtime_path),
        ],
        check=True,
    )
    synced_path = synced_root / operator / "verified-inference" / "inference.md"
    metadata, _ = _frontmatter(synced_path.read_text())
    metadata["use_case"] = (
        "Use for paid OpenAI-compatible CPU inference when live performance "
        "metrics and an AMD SEV-SNP-bound signed receipt are required."
    )

    provider_dir = GENERATED / "catalog" / "providers" / operator / "inference"
    provider_dir.mkdir(parents=True, exist_ok=True)
    paymd = provider_dir / "PAY.md"
    paymd.write_text(
        "---\n"
        + yaml.safe_dump(metadata, sort_keys=False).rstrip()
        + "\n---\n\n"
        + _provider_body()
    )
    emit_openapi(provider_dir / "openapi.json", service_url)

    # Keep repository-level artifacts byte-identical to the generated catalog
    # candidate used by the validator.
    (PAY_ROOT / "PAY.md").write_bytes(paymd.read_bytes())
    (PAY_ROOT / "openapi.json").write_bytes(
        (provider_dir / "openapi.json").read_bytes()
    )

    catalog_root = GENERATED / "catalog"
    relative_paymd = paymd.relative_to(catalog_root)
    command = ["pay", "catalog", "check", str(relative_paymd)]
    if not probe:
        command.append("--no-probe")
    subprocess.run(command, cwd=catalog_root, check=True)
    print(f"wrote and validated {paymd}")
    if network != "mainnet" or not probe:
        print("NOT PUBLISHABLE: mainnet plus a successful live probe are required")
    return paymd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin-url", default="http://127.0.0.1:8477")
    parser.add_argument("--service-url", default="https://pay.example.invalid")
    parser.add_argument("--operator", default="catmcgee")
    parser.add_argument(
        "--network", choices=("localnet", "devnet", "mainnet"), default="localnet"
    )
    parser.add_argument("--max-request-usd", type=float, default=0.50)
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.probe and not args.live_check:
        parser.error("--probe requires --live-check")
    build_provider(
        origin_url=args.origin_url,
        service_url=args.service_url,
        operator=args.operator,
        network=args.network,
        max_request_usd=args.max_request_usd,
        live_check=args.live_check,
        probe=args.probe,
    )


if __name__ == "__main__":
    main()
