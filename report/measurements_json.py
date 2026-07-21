"""Emit web/public/measurements.json — every real measurement, for the frontend.

Reads the runs/ JSONL and distills the results the report tells: TEE tax
(STREAM + inference), thread-saturation sweep, per-model throughput + price,
leg-C API latency, devnet CU, HPKE overhead. Regenerate after new runs.
"""

from __future__ import annotations

import json
import re
import statistics as st
from collections import defaultdict
from pathlib import Path

import jsonschema

from report.analysis import discard_request_warmups

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"


def _rows(name):
    p = RUNS / name
    return (
        [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
        if p.exists()
        else []
    )


def _med(xs):
    xs = list(xs)
    return round(st.median(xs), 3) if xs else None


def _all_request_rows() -> tuple[list[dict], int]:
    """Return every unique frozen-schema request across all run artifacts.

    Curated files intentionally duplicate source records. Identical run IDs are
    collapsed; a conflicting reuse fails rather than silently choosing a copy.
    """
    schema = json.loads((ROOT / "harness" / "schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    by_id: dict[str, dict] = {}
    stored = 0
    for path in sorted(RUNS.glob("*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not validator.is_valid(row):
                continue
            stored += 1
            previous = by_id.get(row["run_id"])
            if previous is not None and previous != row:
                raise ValueError(
                    f"conflicting request record for run_id={row['run_id']}"
                )
            by_id[row["run_id"]] = row
    rows = sorted(by_id.values(), key=lambda row: (row["ts"], row["run_id"]))
    return rows, stored


def main() -> None:
    out = {
        "generated_from": "all schema-valid runs/*.jsonl request records + runs/all-sessions.jsonl",
        "provenance": {},
    }
    curated_raw = _rows("real-requests.jsonl")
    curated, curated_warmups = discard_request_warmups(curated_raw)
    all_requests, stored_request_rows = _all_request_rows()
    _, all_warmups = discard_request_warmups(all_requests)
    session_raw = _rows("all-sessions.jsonl")
    out["request_measurements"] = {
        "rows": all_requests,
        "warmup_run_ids": [row["run_id"] for row in all_warmups],
        "note": (
            "Every unique frozen-schema request in runs/. Identical copies in "
            "source and curated files are shown once."
        ),
    }
    out["session_measurements"] = {
        "rows": session_raw,
        "note": "Every frozen-schema measurement session record.",
    }

    # --- STREAM anchor (memory-encryption tax) ---
    sess = {r["session_id"]: r for r in session_raw}
    stream = {k: v["stream_triad_gbs"] for k, v in sess.items()}
    off = stream.get("legA-plainvm-sevoff")
    es = stream.get("legB-sevescvm-es")
    out["stream_anchor"] = {
        "bare_metal_gbs": stream.get("recon-baremetal-sevoff-20260716"),
        "plain_vm_gbs": off,
        "sev_es_gbs": es,
        "sev_es_tax_pct": round((off - es) / off * 100, 1) if off and es else None,
        "snp_cvm_gbs": stream.get("legB-snpcvm-snp"),
        "note": "STREAM triad, 32 vCPU, identical VMs; pure-bandwidth worst case. "
        "The SNP CVM figure is a KDS-verified separate run (different "
        "kernel/day), shown as a context anchor — not a matched SEV-off↔SNP "
        "tax pair.",
    }

    # --- thread-saturation sweep (tok/s by threads, prompt128/out128) ---
    sweep = defaultdict(dict)
    agg = defaultdict(list)
    for r in _rows("legA-full.jsonl"):
        if r["prompt_tokens"] == 128 and r["output_tokens"] == 128:
            agg[(r["model"], r["threads"])].append(r["tokens_per_s"])
    for (model, threads), v in agg.items():
        sweep[model][str(threads)] = _med(v)
    out["thread_sweep"] = {
        "unit": "tokens_per_s",
        "by_model_threads": sweep,
        "note": "peaks at 32-64 threads, regresses at 128 (bandwidth wall).",
    }

    # --- per-model inference tax (leg A off vs leg B es) ---
    ab = defaultdict(lambda: defaultdict(list))
    for r in _rows("legAB-inference.jsonl"):
        ab[r["model"]][r["sev_mode"]].append(r["tokens_per_s"])
    tax = {}
    for model, bymode in ab.items():
        a, b = _med(bymode.get("off", [])), _med(bymode.get("es", []))
        tax[model] = {
            "plain_vm_tok_s": a,
            "sev_es_tok_s": b,
            "tax_pct": round((a - b) / a * 100, 1) if a and b else None,
        }
    out["inference_tax"] = {
        "by_model": tax,
        "finding": (
            "Historical matched SEV-ES model runs changed by about 2%. "
            "STREAM is a separate memory-only stress test, not an inference "
            "slowdown measurement."
        ),
    }

    # --- pricing + throughput per model (from registry) ---
    import yaml

    reg = {e["id"]: e for e in yaml.safe_load((ROOT / "models.yaml").read_text())}
    out["models"] = [
        {
            "id": e["id"],
            "quant": e["quant"],
            "price_per_1m_in_usdc": e.get("price_per_1m_in_usdc"),
            "price_per_1m_out_usdc": e.get("price_per_1m_out_usdc"),
        }
        for e in reg.values()
    ]

    # --- full matched plain/SNP matrix ---
    plain = [
        r
        for r in curated
        if r["leg"] == "A"
        and r["sev_mode"] == "off"
        and r["numa_policy"] == "guest-single-numa"
    ]
    snp = [
        r
        for r in curated
        if r["leg"] == "B"
        and r["sev_mode"] == "snp"
        and r["numa_policy"] == "guest-single-numa"
    ]
    primary_shape = {
        "threads": 32,
        "prompt_tokens": 128,
        "output_tokens": 128,
        "concurrency": 1,
        "input_mode": "tls",
    }
    primary_open_models = {}
    snp_tax = defaultdict(list)
    for model in sorted({r["model"] for r in plain + snp}):
        for threads in (16, 32):
            for prompt_tokens in (128, 1024):

                def same_shape(row):
                    return (
                        row["model"] == model
                        and row["threads"] == threads
                        and row["prompt_tokens"] == prompt_tokens
                        and row["concurrency"] == 1
                        and row["input_mode"] == "tls"
                    )

                a = [row for row in plain if same_shape(row)]
                b = [row for row in snp if same_shape(row)]
                if a and b:
                    av = _med(r["tokens_per_s"] for r in a)
                    bv = _med(r["tokens_per_s"] for r in b)
                    snp_tax[model].append(round((av - bv) / av * 100, 3))

        def matches_primary_shape(row):
            return (
                row["model"] == model
                and row["threads"] == primary_shape["threads"]
                and row["prompt_tokens"] == primary_shape["prompt_tokens"]
                and row["output_tokens"] == primary_shape["output_tokens"]
                and row["concurrency"] == primary_shape["concurrency"]
                and row["input_mode"] == primary_shape["input_mode"]
            )

        primary_plain = [row for row in plain if matches_primary_shape(row)]
        primary_snp = [row for row in snp if matches_primary_shape(row)]
        if primary_plain and primary_snp:
            plain_tok_s = _med(row["tokens_per_s"] for row in primary_plain)
            snp_tok_s = _med(row["tokens_per_s"] for row in primary_snp)
            primary_open_models[model] = {
                "without_tee_tok_s": plain_tok_s,
                "snp_tee_tok_s": snp_tok_s,
                "tee_slowdown_pct": round(
                    (plain_tok_s - snp_tok_s) / plain_tok_s * 100, 1
                ),
                "samples_per_route": min(len(primary_plain), len(primary_snp)),
            }

    out["route_throughput"] = {
        "unit": "tokens_per_s",
        "shape": primary_shape,
        "open_models": primary_open_models,
        "note": (
            "Median decode throughput for matched, warmed single-request tests. "
            "Compare within each model pair; different model families do "
            "different amounts of work per generated token."
        ),
    }
    if snp_tax:
        out["snp_twin"] = {
            "by_model": {
                model: {
                    "tax_pct_median": _med(values),
                    "tax_pct_min": round(min(values), 3),
                    "tax_pct_max": round(max(values), 3),
                    "matched_cells": len(values),
                }
                for model, values in snp_tax.items()
            },
            "note": "Exact cloned-disk plain/SNP twin; medians exclude the first two raw requests per cell.",
        }

    # --- signed-bound HPKE overhead inside the SNP guest ---
    hpke_by_model = {}
    for model in sorted({r["model"] for r in snp}):

        def common_shape(row):
            return (
                row["model"] == model
                and row["threads"] == 32
                and row["prompt_tokens"] == 128
                and row["concurrency"] == 1
            )

        tls = [row for row in snp if common_shape(row) and row["input_mode"] == "tls"]
        hpke = [row for row in snp if common_shape(row) and row["input_mode"] == "hpke"]
        if tls and hpke:
            tls_ms = _med(r["e2e_ms"] for r in tls)
            hpke_ms = _med(r["e2e_ms"] for r in hpke)
            hpke_by_model[model] = {
                "tls_e2e_ms": tls_ms,
                "hpke_e2e_ms": hpke_ms,
                "delta_ms": round(hpke_ms - tls_ms, 3),
                "attest_fetch_ms": _med(r["attest_fetch_ms"] for r in hpke),
                "attest_verify_ms": _med(r["attest_verify_ms"] for r in hpke),
            }
    out["hpke"] = {
        "by_model": hpke_by_model,
        "delta_ms_median": _med(v["delta_ms"] for v in hpke_by_model.values()),
        "note": "Observed non-interleaved E2E delta, not isolated crypto cost. The signed HPKE-key binding is verified before encryption; each request also includes attestation fetch and verification.",
    }

    # --- leg C: matched direct-versus-SNP-proxied Claude streaming ---
    leg_c_id = re.compile(r"C-(?:direct|proxied)-\d+-\d+-c\d+-\d+").fullmatch
    c_raw = [
        r
        for r in curated_raw
        if r["leg"] in ("C-direct", "C-proxied") and leg_c_id(r["run_id"])
    ]
    c = [
        r
        for r in curated
        if r["leg"] in ("C-direct", "C-proxied") and leg_c_id(r["run_id"])
    ]
    if not c:
        c_raw = _rows("legC-full.jsonl")
        c, _ = discard_request_warmups(c_raw)
    if c:
        direct = [r for r in c if r["leg"] == "C-direct"]
        proxied = [r for r in c if r["leg"] == "C-proxied"]

        def output_cap(record):
            return int(record["run_id"].split("-")[3])

        shape_deltas = []
        shapes = {(r["prompt_tokens"], output_cap(r), r["concurrency"]) for r in c}
        for prompt_tokens, cap, concurrency in shapes:

            def matches_shape(row):
                return (
                    row["prompt_tokens"] == prompt_tokens
                    and output_cap(row) == cap
                    and row["concurrency"] == concurrency
                )

            d = [row for row in direct if matches_shape(row)]
            p = [row for row in proxied if matches_shape(row)]
            if d and p:
                shape_deltas.append(
                    _med(r["ttft_ms"] for r in p) - _med(r["ttft_ms"] for r in d)
                )
        out["leg_c_api"] = {
            "model": c[0]["model"],
            "ttft_ms_median": _med(r["ttft_ms"] for r in direct),
            "e2e_ms_median": _med(r["e2e_ms"] for r in direct),
            "n": len(direct),
            "proxied_ttft_ms_median": _med(r["ttft_ms"] for r in proxied),
            "proxied_e2e_ms_median": _med(r["e2e_ms"] for r in proxied),
            "proxied_n": len(proxied),
            "matched_shape_ttft_delta_ms": _med(shape_deltas),
            "raw_n": len(c_raw),
            "note": "E2E is observational when provider stop lengths differ; the matched-shape TTFT delta is the proxy comparison.",
        }

        primary_direct = [
            row
            for row in direct
            if row["prompt_tokens"] == primary_shape["prompt_tokens"]
            and output_cap(row) == primary_shape["output_tokens"]
            and row["concurrency"] == primary_shape["concurrency"]
        ]
        primary_proxied = [
            row
            for row in proxied
            if row["prompt_tokens"] == primary_shape["prompt_tokens"]
            and output_cap(row) == primary_shape["output_tokens"]
            and row["concurrency"] == primary_shape["concurrency"]
        ]
        if primary_direct and primary_proxied:
            direct_tok_s = _med(row["tokens_per_s"] for row in primary_direct)
            proxied_tok_s = _med(row["tokens_per_s"] for row in primary_proxied)
            out["route_throughput"]["claude_api"] = {
                "model": c[0]["model"],
                "direct_tok_s": direct_tok_s,
                "snp_proxy_tok_s": proxied_tok_s,
                "proxy_slowdown_pct": round(
                    (direct_tok_s - proxied_tok_s) / direct_tok_s * 100, 1
                ),
                "samples_per_route": min(
                    len(primary_direct), len(primary_proxied)
                ),
                "note": (
                    "Anthropic performs inference in both routes. The SNP "
                    "route adds the attested proxy; the small measured "
                    "difference is within normal provider and network variation."
                ),
            }

    # --- on-chain economics, preserving the measured network for each value ---
    cu = json.loads((ROOT / "solana" / "cu-measurements.json").read_text())
    devnet_cu = cu["devnet"]
    out["onchain_devnet"] = {
        "program_id": cu["program_id"],
        "register_attestation_cu": devnet_cu["register_attestation_cu"],
        "post_receipt_cu": devnet_cu["post_receipt_cu"],
        "devnet_measured_at": devnet_cu["measured_at"],
        "note": "Register and receipt costs were measured on devnet.",
    }
    out["provenance"] = {
        "stream_rows": "runs/legAB-stream.jsonl",
        "sweep_rows": "runs/legA-full.jsonl (320)",
        "inference_tax_rows": "runs/legAB-inference.jsonl (60)",
        "matched_rows": f"runs/real-requests.jsonl ({len(curated_raw)} raw; {len(curated)} retained)",
        "all_request_rows": (
            f"{len(all_requests)} unique from {stored_request_rows} stored schema-valid rows"
        ),
        "warmups_excluded": str(len(curated_warmups)),
        "leg_c_rows": f"runs/legC-full.jsonl ({len(c_raw)} raw)",
        "measured": "2026-07-16 to 2026-07-17",
    }

    web = ROOT / "web" / "public"
    web.mkdir(parents=True, exist_ok=True)
    (web / "measurements.json").write_text(json.dumps(out, indent=2))
    print("wrote web/public/measurements.json")
    print(
        f"  stream tax {out['stream_anchor']['sev_es_tax_pct']}% | "
        f"inference tax { {m: t['tax_pct'] for m, t in tax.items()} }"
    )


if __name__ == "__main__":
    main()
