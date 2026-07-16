"""vinfer — infer / attest / verify / bench / receipts.

Verification pipeline (PLAN.md): attestation → AMD KDS chain → key binding →
registry PDA → receipt sig → on-chain record. In P0 only the steps that can be
real ARE real (ed25519 receipt sig, key binding); hardware/chain steps print
SKIPPED with the reason rather than pretending.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path

import click
import httpx

BASE_URL = os.environ.get("VINFER_URL", "http://127.0.0.1:8477")


def _get(path: str) -> dict:
    r = httpx.get(f"{BASE_URL}{path}", timeout=60)
    r.raise_for_status()
    return r.json()


@click.group()
def cli():
    """verified-inference CLI."""


@cli.command()
@click.option("--model", required=True)
@click.option("--prompt", required=True)
@click.option("--max-tokens", default=64, show_default=True)
@click.option("--receipt-out", type=click.Path(dir_okay=False), help="Write the signed receipt JSON here")
def infer(model: str, prompt: str, max_tokens: int, receipt_out: str | None):
    """Run one inference and print live metrics."""
    r = httpx.post(
        f"{BASE_URL}/v1/infer",
        json={"model": model, "prompt": prompt, "max_tokens": max_tokens},
        timeout=600,
    )
    r.raise_for_status()
    body = r.json()
    click.echo(body["text"])
    m = body["metrics"]
    click.echo(
        f"\n[{model}] ttft {m['ttft_ms']}ms · {m['tokens_per_s']} tok/s · "
        f"itl p50/p99 {m['itl_ms_p50']}/{m['itl_ms_p99']}ms · e2e {m['e2e_ms']}ms · "
        f"sev={m['sev_mode']} · backend={m['backend']} · receipt {body['receipt']['receipt_id']}",
        err=True,
    )
    if receipt_out:
        Path(receipt_out).parent.mkdir(parents=True, exist_ok=True)
        Path(receipt_out).write_text(json.dumps(body["receipt"], indent=2))
        click.echo(f"receipt → {receipt_out}", err=True)


@cli.command()
def attest():
    """Fetch and display the server's attestation document."""
    doc = _get("/v1/attestation")
    click.echo(json.dumps(doc, indent=2))
    if doc["grade"] != "snp":
        click.echo(f"\ngrade={doc['grade']}: {doc['note']}", err=True)


@cli.command()
@click.argument("receipt_file", type=click.Path(exists=True, dir_okay=False))
def verify(receipt_file: str):
    """Verify a receipt: each pipeline step prints PASS / FAIL / SKIPPED."""
    from server.receipts.signer import verify_receipt  # offline ed25519 check

    receipt = json.loads(Path(receipt_file).read_text())
    failed = False

    def step(name: str, status: str, detail: str = ""):
        nonlocal failed
        if status == "FAIL":
            failed = True
        click.echo(f"  [{status:^7}] {name}" + (f" — {detail}" if detail else ""))

    click.echo(f"verifying {receipt_file}")

    try:
        att = _get("/v1/attestation")
    except Exception as e:
        att = None
        step("fetch attestation", "FAIL", str(e))

    if att:
        if att["grade"] == "snp":
            step("SNP report → AMD KDS (VCEK/ASK/ARK) chain", "TODO", "P3 wires the real check")
        else:
            step(
                "SNP report → AMD KDS chain",
                "SKIPPED",
                f"attestation grade is '{att['grade']}' — no hardware report exists; a verifier can conclude nothing here",
            )
        binding = "PASS" if att["enclave_pubkey_b64"] == receipt["enclave_pubkey_b64"] else "FAIL"
        step("enclave key binding (attestation ↔ receipt)", binding)
        bv = att.get("binding_version", 1)
        if bv == 2:
            mid = bytes.fromhex(att["registry_hash"])
            label = "REPORT_DATA v2 = sha256(pubkey ‖ registry_hash ‖ build)"
        else:
            mid = bytes.fromhex(att["model_weights_hash"])
            label = "REPORT_DATA v1 = sha256(pubkey ‖ weights ‖ build)"
        expected = hashlib.sha256(
            base64.b64decode(att["enclave_pubkey_b64"]) + mid
            + bytes.fromhex(att["server_build_hash"])
        ).hexdigest()
        step(label, "PASS" if expected == att["report_data"] else "FAIL",
             f"binding_version={bv}")
        if bv == 2:
            reg = {e["id"]: e["weights_sha256"] for e in att.get("registry", [])}
            in_reg = receipt["model_hash"] in reg.values()
            step("receipt model_hash ∈ attested registry", "PASS" if in_reg else "FAIL")

    step("registry PDA lookup (Solana)", "SKIPPED", "devnet posting lands in P2")
    step("receipt ed25519 signature", "PASS" if verify_receipt(receipt) else "FAIL")
    step("on-chain receipt record", "SKIPPED", "devnet posting lands in P2")

    click.echo("RESULT: " + ("FAIL" if failed else "OK (with skips as noted)"))
    sys.exit(1 if failed else 0)


@cli.command()
@click.option("--matrix", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--out", required=True, type=click.Path(dir_okay=False))
def bench(matrix: str, out: str):
    """Run the experiment matrix against the server → schema-valid JSONL (resumable)."""
    from harness.runner import run

    summary = run(matrix, out, base_url=BASE_URL)
    click.echo(json.dumps(summary, indent=2))


@cli.command()
@click.argument("receipt_id")
def receipts(receipt_id: str):
    """Fetch a receipt by id."""
    click.echo(json.dumps(_get(f"/v1/receipts/{receipt_id}"), indent=2))


if __name__ == "__main__":
    cli()
