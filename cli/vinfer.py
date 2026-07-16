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

    # on-chain checks (devnet read-path; enclave keys are only on-chain once
    # register_attestation ran for them — absent PDA is reported, not failed)
    try:
        from cli import devnet

        enclave_raw = base64.b64decode(receipt["enclave_pubkey_b64"])
        chain = devnet.check_onchain(enclave_raw)
        if chain is None:
            step("registry PDA lookup (Solana devnet)", "ABSENT",
                 "this enclave key is not registered on-chain (register_attestation not run for it)")
        else:
            step("registry PDA lookup (Solana devnet)", "PASS",
                 f"grade={chain['attestation_grade']} binding_v{chain['binding_version']} slot={chain['slot']}")
            if att and att.get("binding_version", 1) == 2 and chain["binding_version"] == 2:
                match = chain["registry_hash"] == att.get("registry_hash")
                step("on-chain registry_hash == served registry_hash",
                     "PASS" if match else "FAIL")
        step("receipt ed25519 signature", "PASS" if verify_receipt(receipt) else "FAIL")
        if chain is not None and chain["receipt_count"] > 0:
            found = any(devnet.check_receipt(enclave_raw, i) for i in range(min(chain["receipt_count"], 8)))
            step("on-chain receipt record", "PASS" if found else "FAIL",
                 f"{chain['receipt_count']} receipt(s) registered for this enclave")
        else:
            step("on-chain receipt record", "ABSENT", "no receipts posted for this enclave")
    except Exception as e:
        step("Solana devnet checks", "SKIPPED", f"rpc unavailable: {e}")
        step("receipt ed25519 signature", "PASS" if verify_receipt(receipt) else "FAIL")

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


@cli.command()
@click.option("--model", default="bitnet-2b", show_default=True)
@click.option("--prompt", default="What is memory-bandwidth-bound inference?", show_default=True)
@click.option("--max-tokens", default=64, show_default=True)
@click.option("--deposit-usdc", default=1.0, show_default=True, help="channel deposit to authorize")
def pay(model: str, prompt: str, max_tokens: int, deposit_usdc: float):
    """Exercise the x402 session-payment flow end to end (test client).

    Runs: unpaid request → 402 challenge → open channel → sign a cumulative
    voucher → paid metered request → prints the Payment-Receipt + settlement.
    Uses a local ed25519 signer to stand in for the on-chain channel signer.
    """
    import base64 as b64
    from nacl.signing import SigningKey
    from server.x402.session import voucher_message

    def _b58(raw: bytes) -> str:
        try:
            from solders.pubkey import Pubkey
            return str(Pubkey.from_bytes(raw)) if len(raw) == 32 else b64.b64encode(raw).decode()
        except Exception:
            return b64.b64encode(raw).decode()

    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}

    # 1. unpaid → expect 402 challenge
    r = httpx.post(f"{BASE_URL}/v1/chat/completions", json=body, timeout=600)
    if r.status_code != 402:
        click.echo("server is not x402-gated (VINFER_X402!=1); response was "
                   f"{r.status_code}. The free path works:", err=True)
        click.echo(r.json().get("x_vinfer", {}).get("metrics", r.json()))
        return
    ch = r.json()["accepts"][0]
    click.echo(f"402 challenge: {ch['scheme']} on {ch['network']}, quote "
               f"{ch['amount']['quote_micro_usdc']} micro-USDC, asset {ch['assetSymbol']}")

    # 2. open a channel (local signer stands in for the on-chain authorizedSigner)
    signer = SigningKey.generate()
    signer_pub = bytes(signer.verify_key)
    channel_kp = SigningKey.generate()               # channel PDA stand-in (32 bytes)
    channel_bytes = bytes(channel_kp.verify_key)
    channel_b58 = _b58(channel_bytes)
    deposit_micro = int(deposit_usdc * 1_000_000)

    def auth_header(payload: dict) -> dict:
        raw = b64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        return {"authorization": f"Payment {raw}"}

    r = httpx.post(f"{BASE_URL}/v1/chat/completions", json=body, timeout=600,
                   headers=auth_header({"action": "open", "channelId": channel_b58,
                                        "authorizedSigner": _b58(signer_pub),
                                        "deposit": deposit_micro}))
    click.echo(f"open → {r.json().get('status', r.json())}")

    # 3. sign a cumulative voucher covering the quote and send a paid request
    cumulative = deposit_micro   # authorize the whole deposit
    sig = signer.sign(voucher_message(channel_bytes, cumulative, 0)).signature
    voucher = {"channelId": channel_b58, "cumulativeAmount": str(cumulative),
               "expiresAt": 0, "signer": _b58(signer_pub),
               "signature": b64.b64encode(sig).decode()}
    r = httpx.post(f"{BASE_URL}/v1/chat/completions", json=body, timeout=600,
                   headers=auth_header({"action": "voucher", "voucher": voucher}))
    if r.status_code != 200:
        click.echo(f"paid request failed [{r.status_code}]: {r.json()}", err=True)
        sys.exit(1)
    d = r.json()
    click.echo("\n" + d["choices"][0]["message"]["content"])
    m = d["x_vinfer"]["metrics"]
    s = d["x_vinfer"]["settlement"]
    click.echo(f"\n[{model}] {m['tokens_per_s']} tok/s · receipt {d['x_vinfer']['receipt']['receipt_id']}", err=True)
    click.echo(f"Payment-Receipt: {r.headers.get('Payment-Receipt')}", err=True)
    click.echo(f"settlement: quoted {s['quote_micro_usdc']} → charged "
               f"{s['charged_micro_usdc']} (refunded {s['refunded_micro_usdc']}) micro-USDC; "
               f"channel available {s['available_micro_usdc']}", err=True)


if __name__ == "__main__":
    cli()
