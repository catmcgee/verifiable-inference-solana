"""vinfer — infer / attest / verify / bench / receipts.

Verification pipeline: attestation → AMD KDS chain → key binding →
registry PDA → receipt sig → on-chain record. In P0 only the steps that can be
real ARE real (ed25519 receipt sig, key binding); hardware/chain steps print
SKIPPED with the reason rather than pretending.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import click
import httpx

BASE_URL = os.environ.get("VINFER_URL", "http://127.0.0.1:8477")
PAY_URL = os.environ.get("VINFER_PAY_URL", BASE_URL)


def _auth_headers() -> dict[str, str]:
    token = os.environ.get("VINFER_AUTH_TOKEN")
    return {"authorization": f"Bearer {token}"} if token else {}


def _get(path: str) -> dict:
    r = httpx.get(f"{BASE_URL}{path}", timeout=60, headers=_auth_headers())
    r.raise_for_status()
    return r.json()


@click.group()
def cli():
    """verified-inference CLI."""


@cli.command()
@click.option("--model", required=True)
@click.option("--prompt", required=True)
@click.option("--max-tokens", default=64, show_default=True)
@click.option(
    "--receipt-out",
    type=click.Path(dir_okay=False),
    help="Write the signed receipt JSON here",
)
@click.option(
    "--e2e",
    is_flag=True,
    help="Attestation-gated end-to-end sealed session (both directions)",
)
@click.option(
    "--insecure-allow-unattested",
    is_flag=True,
    help="For --e2e: accept a signed HPKE key without hardware attestation",
)
def infer(
    model: str,
    prompt: str,
    max_tokens: int,
    receipt_out: str | None,
    e2e: bool,
    insecure_allow_unattested: bool,
):
    """Run one chat completion. --e2e verifies attestation and seals both
    directions; the default uses the OpenAI-compatible TLS endpoint."""
    if e2e:
        from cli.attest_verify import verify_attestation
        from server.crypto.session_box import client_open_session, client_open_response

        doc = _get("/v1/attestation")
        v = verify_attestation(doc, allow_unattested=insecure_allow_unattested)
        mark = "PASS" if v.trusted else "REFUSE"
        click.echo(
            f"[attest {mark}] grade={v.grade} binding_ok={v.binding_ok} "
            f"kds_ok={v.kds_ok}",
            err=True,
        )
        click.echo(f"           {v.reason}", err=True)
        if not v.trusted:
            click.echo("aborting e2e session — enclave key not trusted.", err=True)
            sys.exit(2)
        messages = [{"role": "user", "content": prompt}]
        plaintext = json.dumps(
            {"schema": "vinfer-e2e-chat-v1", "messages": messages},
            separators=(",", ":"),
        ).encode()
        wire, session_key = client_open_session(doc["hpke_public_key_b64"], plaintext)
        r = httpx.post(
            f"{BASE_URL}/v1/chat_e2e",
            json={
                "model": model,
                "enc": wire["enc"],
                "ciphertext": wire["ciphertext"],
                "max_tokens": max_tokens,
            },
            headers=_auth_headers(),
            timeout=600,
        )
        r.raise_for_status()
        d = r.json()
        text = client_open_response(
            session_key, d["resp_nonce"], d["sealed_response"]
        ).decode()
        metrics = json.loads(
            client_open_response(
                session_key,
                d["sealed_metrics"]["resp_nonce"],
                d["sealed_metrics"]["sealed_response"],
            ).decode()
        )
        click.echo(text)
        click.echo(
            f"\n[{model}] e2e-sealed · {metrics['tokens_per_s']} tok/s · "
            f"decrypted client-side · receipt {d['receipt']['receipt_id']}",
            err=True,
        )
        if receipt_out:
            Path(receipt_out).parent.mkdir(parents=True, exist_ok=True)
            Path(receipt_out).write_text(json.dumps(d["receipt"], indent=2))
            click.echo(f"receipt → {receipt_out}", err=True)
        return
    r = httpx.post(
        f"{BASE_URL}/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        },
        headers=_auth_headers(),
        timeout=600,
    )
    r.raise_for_status()
    body = r.json()
    click.echo(body["choices"][0]["message"]["content"])
    proof = body["x_vinfer"]
    m = proof["metrics"]
    receipt = proof["receipt"]
    click.echo(
        f"\n[{model}] ttft {m['ttft_ms']}ms · {m['tokens_per_s']} tok/s · "
        f"itl p50/p99 {m['itl_ms_p50']}/{m['itl_ms_p99']}ms · e2e {m['e2e_ms']}ms · "
        f"sev={m['sev_mode']} · backend={m['backend']} · receipt {receipt['receipt_id']}",
        err=True,
    )
    if receipt_out:
        Path(receipt_out).parent.mkdir(parents=True, exist_ok=True)
        Path(receipt_out).write_text(json.dumps(receipt, indent=2))
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
    incomplete = False
    skipped = False

    def step(name: str, status: str, detail: str = ""):
        nonlocal failed, incomplete, skipped
        if status == "FAIL":
            failed = True
        elif status == "ABSENT":
            incomplete = True
        elif status == "SKIPPED":
            skipped = True
        click.echo(f"  [{status:^7}] {name}" + (f" — {detail}" if detail else ""))

    click.echo(f"verifying {receipt_file}")

    # Trust the receipt's OWN attestation doc when it ships one (self-verifiable,
    # offline) — the on-chain PDA cross-check below is the real anchor, not this
    # doc. Fall back to the live server for a freshly-minted receipt.
    att = receipt.get("attestation")
    if att:
        step(
            "attestation source",
            "PASS",
            "embedded in receipt (cross-checked on-chain below)",
        )
    else:
        try:
            att = _get("/v1/attestation")
            step("attestation source", "PASS", "fetched from live server")
        except Exception as e:
            att = None
            step("fetch attestation", "FAIL", str(e))

    if att:
        from cli.attest_verify import verify_attestation

        verdict = verify_attestation(
            att, allow_unattested=True, require_hpke=False
        )
        if att["grade"] == "snp":
            step(
                "SNP report + AMD chain + policy + execution identity + binding",
                "PASS" if verdict.trusted else "FAIL",
                verdict.reason,
            )
        else:
            step(
                "attestation document + execution identity + binding",
                "PASS" if verdict.trusted else "FAIL",
                verdict.reason,
            )
            step(
                "SNP report → AMD KDS chain",
                "SKIPPED",
                f"attestation grade is '{att['grade']}' — no hardware report exists; a verifier can conclude nothing here",
            )
        binding = (
            "PASS"
            if att["enclave_pubkey_b64"] == receipt["enclave_pubkey_b64"]
            else "FAIL"
        )
        step("enclave key binding (attestation ↔ receipt)", binding)
        bv = att.get("binding_version", 1)
        if bv == 2:
            reg = {e["id"]: e["weights_sha256"] for e in att.get("registry", [])}
            in_reg = receipt["model_hash"] in reg.values()
            step("receipt model_hash ∈ attested registry", "PASS" if in_reg else "FAIL")

    # on-chain checks (devnet read-path; enclave keys are only on-chain once
    # register_attestation ran for them — absent PDA is reported, not failed)
    try:
        from server.receipts import solana as devnet

        enclave_raw = base64.b64decode(receipt["enclave_pubkey_b64"])
        chain = devnet.check_onchain(enclave_raw)
        if chain is None:
            step(
                "registry PDA lookup (Solana devnet)",
                "ABSENT",
                "this enclave key is not registered on-chain (register_attestation not run for it)",
            )
        else:
            step(
                "registry PDA lookup (Solana devnet)",
                "PASS",
                f"grade={chain['attestation_grade']} binding_v{chain['binding_version']} slot={chain['slot']}",
            )
            if att:
                metadata_match = (
                    chain["enclave_pubkey"]
                    == base64.b64decode(att["enclave_pubkey_b64"]).hex()
                    and chain["attestation_grade"] == att.get("grade")
                    and chain["binding_version"] == att.get("binding_version", 1)
                    and chain["runtime_version"] == att.get("runtime_version")
                )
                step(
                    "on-chain enclave grade/runtime/binding metadata",
                    "PASS" if metadata_match else "FAIL",
                )
                rd_match = chain["report_data_hash"] == att.get("report_data")
                step(
                    "on-chain REPORT_DATA == attestation report_data",
                    "PASS" if rd_match else "FAIL",
                    "the PDA independently anchors the enclave-key binding",
                )
                if att.get("grade") == "snp" and att.get("snp_report_b64"):
                    report_measurement = base64.b64decode(att["snp_report_b64"])[
                        0x90:0xC0
                    ].hex()
                    step(
                        "on-chain measurement == signed SNP report",
                        "PASS"
                        if chain["snp_measurement"] == report_measurement
                        else "FAIL",
                    )
            if (
                att
                and att.get("binding_version", 1) == 2
                and chain["binding_version"] == 2
            ):
                match = chain["registry_hash"] == att.get("registry_hash")
                step(
                    "on-chain registry_hash == served registry_hash",
                    "PASS" if match else "FAIL",
                )
        step("receipt ed25519 signature", "PASS" if verify_receipt(receipt) else "FAIL")
        if chain is not None and chain["receipt_count"] > 0:
            expected_receipt = {
                "enclave_pubkey": enclave_raw.hex(),
                "prompt_hash": receipt["prompt_hash"],
                "response_hash": receipt["response_hash"],
                "model_hash": receipt["model_hash"],
                "timestamp": receipt["timestamp"],
            }
            matched_index = None
            supplied_index = receipt.get("receipt_index")
            if supplied_index is not None:
                indexes = [int(supplied_index)]
            elif chain["receipt_count"] > 10_000:
                raise RuntimeError(
                    "receipt index is not embedded and the enclave has more than "
                    "10,000 receipts; re-export the receipt with on-chain index metadata"
                )
            else:
                indexes = range(chain["receipt_count"])
            for i in indexes:
                posted = devnet.check_receipt(enclave_raw, i)
                if posted and all(posted[k] == v for k, v in expected_receipt.items()):
                    matched_index = i
                    break
            if matched_index is not None and receipt.get("receipt_pda"):
                expected_pda = str(devnet.receipt_pda(enclave_raw, matched_index))
                step(
                    "receipt PDA address",
                    "PASS" if receipt["receipt_pda"] == expected_pda else "FAIL",
                )
            step(
                "exact receipt contents anchored on-chain",
                "PASS" if matched_index is not None else "FAIL",
                f"matched receipt index {matched_index}"
                if matched_index is not None
                else f"no match among {chain['receipt_count']} posted receipt(s)",
            )
        else:
            step(
                "on-chain receipt record",
                "ABSENT",
                "no receipts posted for this enclave",
            )
    except Exception as e:
        step("Solana devnet checks", "SKIPPED", f"rpc unavailable: {e}")
        step("receipt ed25519 signature", "PASS" if verify_receipt(receipt) else "FAIL")

    if failed:
        result, exit_code = "FAIL", 1
    elif incomplete:
        result, exit_code = "INCOMPLETE (required on-chain evidence absent)", 2
    elif skipped:
        result, exit_code = "OK (with cryptographic skips as noted)", 0
    else:
        result, exit_code = "OK", 0
    click.echo(f"RESULT: {result}")
    sys.exit(exit_code)


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
@click.option(
    "--prompt", default="What is memory-bandwidth-bound inference?", show_default=True
)
@click.option("--max-tokens", default=64, show_default=True)
@click.option("--sandbox", is_flag=True, help="Use pay's sandbox wallet; no real funds")
def pay(model: str, prompt: str, max_tokens: int, sandbox: bool):
    """Call the paid gateway through the official pay CLI."""
    if shutil.which("pay") is None:
        raise click.ClickException("pay CLI not found; install it from https://pay.sh")
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    command = ["pay"]
    if sandbox:
        command.append("--sandbox")
    command.extend(
        [
            "curl",
            "-sS",
            "-X",
            "POST",
            f"{PAY_URL}/v1/chat/completions",
            "-H",
            "content-type: application/json",
            "--data",
            json.dumps(body, separators=(",", ":")),
        ]
    )
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise click.ClickException(result.stderr.strip() or "paid request failed")
    try:
        response = json.loads(result.stdout)
        click.echo(response["choices"][0]["message"]["content"])
        proof = response.get("x_vinfer", {})
        receipt_id = proof.get("receipt", {}).get("receipt_id", "missing")
        grade = proof.get("attestation_grade", "missing")
        click.echo(f"receipt {receipt_id} · attestation grade {grade}", err=True)
    except (json.JSONDecodeError, KeyError, IndexError):
        click.echo(result.stdout)


if __name__ == "__main__":
    cli()
