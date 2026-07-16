#!/usr/bin/env python3
"""Deterministic synthetic fixture generator for the verified-inference harness.

Produces:
  harness/fixtures/synthetic.jsonl          — per-request records (harness/schema.json)
  harness/fixtures/synthetic_sessions.jsonl — per-session records (harness/session_schema.json)

Everything is seeded and uses a hardcoded base timestamp — no wall-clock
randomness. Re-running always produces byte-identical output.

The modeled world (P0 synthetic, shapes chosen to look like the real box):
  * Legs A (sev off) and B (sev snp), models {bitnet-2b, 8b-q4, 8b-q8, 70b-q4},
    threads {16,32,64,128}, prompt {128,1024,8192}, output {128,1024},
    concurrency {1,4,8}. n=5 per cell with the first 2 discarded per the
    harness convention -> 3 kept records per cell (sample ids s03..s05).
  * SEV tax on tokens_per_s grows with model size (more bandwidth-bound) and
    with thread count (closer to bandwidth saturation): ~2% for bitnet-2b at
    128 threads up to ~9% for 70b-q4 at 128 threads.
  * Leg C: claude-direct vs claude-via-cvm-proxy; proxy adds ~15-40 ms.
  * Leg D: zkML ladder rungs encoded in the model field ("bitnet-2b-rung1"...)
    because the frozen schema has no rung_id field.

Run:  uv run harness/fixtures/gen_synthetic.py
"""

import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

SEED = 20260710
BASE_TS = datetime(2026, 7, 10, 8, 0, 0, tzinfo=timezone.utc)  # fixed, not wall-clock

# ---------------------------------------------------------------------------
# Model performance parameters (single-stream, 64 threads, sev off)
# decode_tps: tokens/s decode; prefill_tps: prompt eval tokens/s.
# sev_base_tax: fractional throughput tax at the reference point; scaled by
# thread count below (SEV AES memory encryption sits on the bandwidth path,
# so the tax grows as threads push toward bandwidth saturation).
# ---------------------------------------------------------------------------
MODELS = {
    "bitnet-2b": dict(quant="i2_s",   decode_tps=68.0, prefill_tps=560.0, sev_base_tax=0.0125),
    "8b-q4":     dict(quant="Q4_K_M", decode_tps=26.5, prefill_tps=215.0, sev_base_tax=0.034),
    "8b-q8":     dict(quant="Q8_0",   decode_tps=15.8, prefill_tps=185.0, sev_base_tax=0.042),
    "70b-q4":    dict(quant="Q4_K_M", decode_tps=5.3,  prefill_tps=38.0,  sev_base_tax=0.056),
}

# Thread scaling of decode throughput relative to 64 threads.
# Bandwidth-bound models saturate at ~64; SMT (128) is slightly negative.
# bitnet-2b is more compute-bound and still gains a little from SMT.
THREAD_SCALE = {
    "bitnet-2b": {16: 0.36, 32: 0.64, 64: 1.0, 128: 1.10},
    "8b-q4":     {16: 0.55, 32: 0.83, 64: 1.0, 128: 0.97},
    "8b-q8":     {16: 0.57, 32: 0.85, 64: 1.0, 128: 0.96},
    "70b-q4":    {16: 0.60, 32: 0.87, 64: 1.0, 128: 0.95},
}

# SEV tax multiplier by thread count (relative to sev_base_tax).
# At 128 threads the memory path is saturated -> tax peaks:
#   bitnet-2b: 0.0125 * 1.60 ≈ 2.0%   |   70b-q4: 0.056 * 1.60 ≈ 9.0%
SEV_THREAD_MULT = {16: 0.55, 32: 0.78, 64: 1.10, 128: 1.60}

# Per-request throughput factor under concurrency (aggregate rises sublinearly).
CONC_FACTOR = {1: 1.0, 4: 0.47, 8: 0.29}

# Long-context KV overhead on decode.
CTX_PENALTY = {128: 1.0, 1024: 0.985, 8192: 0.92}

THREADS = [16, 32, 64, 128]
PROMPTS = [128, 1024, 8192]
OUTPUTS = [128, 1024]
CONCURRENCY = [1, 4, 8]

N_PER_CELL = 5       # harness convention: n>=5 per cell...
DISCARD_FIRST = 2    # ...discard first 2 (warmup); only kept samples are logged

NUMA_POLICY = "interleave=all"


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def clamp(x: float, lo: float = 0.0) -> float:
    return max(lo, x)


def noisy(rng: random.Random, x: float, sd: float = 0.02) -> float:
    return x * max(0.5, rng.gauss(1.0, sd))


def make_ab_record(rng, ts, leg, model, threads, pt, ot, conc, sample_idx):
    p = MODELS[model]
    sev = leg == "B"
    sev_mode = "snp" if sev else "off"

    sev_tax = p["sev_base_tax"] * SEV_THREAD_MULT[threads] if sev else 0.0
    tps = (
        p["decode_tps"]
        * THREAD_SCALE[model][threads]
        * CONC_FACTOR[conc]
        * CTX_PENALTY[pt]
        * (1.0 - sev_tax)
    )
    tps = noisy(rng, tps, 0.012)  # repeated decode runs on a quiet box are ~1% stable

    # Prefill: bandwidth-bound too; SEV taxes it slightly less than decode.
    prefill_tps = p["prefill_tps"] * (0.55 + 0.45 * THREAD_SCALE[model][threads])
    if sev:
        prefill_tps *= 1.0 - sev_tax * 0.8
    ttft = pt / prefill_tps * 1000.0 + rng.uniform(18, 45) * (1.0 + 0.25 * (conc > 1))
    ttft = noisy(rng, ttft, 0.04)

    itl_p50 = 1000.0 / tps
    itl_p50 = noisy(rng, itl_p50, 0.015)
    tail = rng.uniform(1.22, 1.55) + (0.25 if conc == 8 else 0.08 if conc == 4 else 0.0)
    itl_p99 = itl_p50 * tail

    e2e = ttft + ot * itl_p50 * noisy(rng, 1.0, 0.01)

    if sev:
        attest_fetch = clamp(rng.gauss(46.0, 9.0), 12.0)     # snpguest report (cached VCEK)
        attest_verify = clamp(rng.gauss(21.0, 4.5), 6.0)     # sig -> VCEK -> ASK/ARK
        receipt_sign = clamp(rng.gauss(0.34, 0.05), 0.1)     # ed25519 in-enclave
        receipt_post = clamp(rng.gauss(520.0, 90.0), 200.0)  # devnet tx submit
        receipt_confirm = receipt_post + clamp(rng.gauss(780.0, 240.0), 300.0)
        solana_cu = int(rng.gauss(5150, 160))
        solana_fee = 5000 + int(abs(rng.gauss(60, 40)))
    else:
        attest_fetch = attest_verify = 0.0
        receipt_sign = receipt_post = receipt_confirm = 0.0
        solana_cu = 0
        solana_fee = 0

    run_id = f"{leg}-{model}-t{threads}-p{pt}-o{ot}-c{conc}-s{sample_idx:02d}"
    return {
        "run_id": run_id,
        "leg": leg,
        "model": model,
        "quant": p["quant"],
        "sev_mode": sev_mode,
        "input_mode": "tls",
        "threads": threads,
        "numa_policy": NUMA_POLICY,
        "prompt_tokens": pt,
        "output_tokens": ot,
        "batch": 1,
        "concurrency": conc,
        "ttft_ms": round(ttft, 2),
        "itl_ms_p50": round(itl_p50, 3),
        "itl_ms_p99": round(itl_p99, 3),
        "tokens_per_s": round(tps, 3),
        "e2e_ms": round(e2e, 1),
        "attest_fetch_ms": round(attest_fetch, 2),
        "attest_verify_ms": round(attest_verify, 2),
        "receipt_sign_ms": round(receipt_sign, 3),
        "receipt_post_ms": round(receipt_post, 1),
        "receipt_confirm_ms": round(receipt_confirm, 1),
        "solana_cu": max(0, solana_cu),
        "solana_fee_lamports": max(0, solana_fee),
        "ts": iso(ts),
    }


def make_c_record(rng, ts, path, pt, ot, conc, sample_idx):
    """Leg C: Claude API direct vs via attested CVM proxy."""
    proxied = path == "C-proxied"
    api_tps = noisy(rng, 66.0, 0.06)                       # streamed output tok/s
    ttft = 480.0 + pt * 0.055 + rng.uniform(-60, 140)      # API queue + prefill
    ttft += rng.uniform(30, 120) if conc == 8 else 0.0
    proxy_ms = rng.uniform(15, 40) if proxied else 0.0     # CVM proxy hop
    ttft = clamp(ttft, 180.0) + proxy_ms

    itl_p50 = noisy(rng, 1000.0 / api_tps, 0.03)
    itl_p99 = itl_p50 * rng.uniform(1.6, 2.6)
    e2e = ttft + ot * itl_p50 * noisy(rng, 1.0, 0.015)

    if proxied:
        attest_fetch = 0.0                                  # proxy attestation cached client-side
        attest_verify = clamp(rng.gauss(11.0, 2.5), 4.0)    # cached-cert chain re-check
        receipt_sign = clamp(rng.gauss(0.33, 0.05), 0.1)
        receipt_post = clamp(rng.gauss(520.0, 90.0), 200.0)
        receipt_confirm = receipt_post + clamp(rng.gauss(780.0, 240.0), 300.0)
        solana_cu = int(rng.gauss(5150, 160))
        solana_fee = 5000 + int(abs(rng.gauss(60, 40)))
    else:
        attest_fetch = attest_verify = 0.0
        receipt_sign = receipt_post = receipt_confirm = 0.0
        solana_cu = 0
        solana_fee = 0

    run_id = f"{path}-p{pt}-o{ot}-c{conc}-s{sample_idx:02d}"
    return {
        "run_id": run_id,
        "leg": path,
        "model": "claude-sonnet-4",
        "quant": "api",
        "sev_mode": "snp" if proxied else "off",
        "input_mode": "tls",
        "threads": 0,
        "numa_policy": "n/a",
        "prompt_tokens": pt,
        "output_tokens": ot,
        "batch": 1,
        "concurrency": conc,
        "ttft_ms": round(ttft, 2),
        "itl_ms_p50": round(itl_p50, 3),
        "itl_ms_p99": round(itl_p99, 3),
        "tokens_per_s": round(api_tps, 3),
        "e2e_ms": round(e2e, 1),
        "attest_fetch_ms": round(attest_fetch, 2),
        "attest_verify_ms": round(attest_verify, 2),
        "receipt_sign_ms": round(receipt_sign, 3),
        "receipt_post_ms": round(receipt_post, 1),
        "receipt_confirm_ms": round(receipt_confirm, 1),
        "solana_cu": max(0, solana_cu),
        "solana_fee_lamports": max(0, solana_fee),
        "ts": iso(ts),
    }


# zkML ladder rungs (schema has no rung_id -> encoded in model field).
# prove_s: median proving wall-time, sev off. SEV taxes the (memory-heavy)
# prover roughly like the biggest LLM (~7-9%).
D_RUNGS = {
    "bitnet-2b-rung1": dict(prove_s=44.0,   desc="one ternary matmul"),
    "bitnet-2b-rung2": dict(prove_s=830.0,  desc="one transformer block"),
    "bitnet-2b-rung3": dict(prove_s=3350.0, desc="4 blocks (extrapolation basis)"),
}


def make_d_record(rng, ts, model, sev_mode, sample_idx):
    p = D_RUNGS[model]
    prove_ms = p["prove_s"] * 1000.0
    if sev_mode == "snp":
        prove_ms *= 1.0 + rng.uniform(0.065, 0.095)
    prove_ms = noisy(rng, prove_ms, 0.03)

    receipt_post = clamp(rng.gauss(540.0, 90.0), 200.0)      # groth16 verify tx submit
    run_id = f"D-{model}-sev{sev_mode}-s{sample_idx:02d}"
    return {
        "run_id": run_id,
        "leg": "D",
        "model": model,
        "quant": "ternary",
        "sev_mode": sev_mode,
        "input_mode": "tls",
        "threads": 128,
        "numa_policy": NUMA_POLICY,
        "prompt_tokens": 1,
        "output_tokens": 1,
        "batch": 1,
        "concurrency": 1,
        "ttft_ms": 0.0,
        "itl_ms_p50": 0.0,
        "itl_ms_p99": 0.0,
        "tokens_per_s": 0.0,
        "e2e_ms": round(prove_ms, 1),                        # e2e = proving wall time
        "attest_fetch_ms": 0.0,
        "attest_verify_ms": round(clamp(rng.gauss(6.5, 1.2), 2.0), 2),  # off-chain proof verify
        "receipt_sign_ms": 0.0,
        "receipt_post_ms": round(receipt_post, 1),
        "receipt_confirm_ms": round(receipt_post + clamp(rng.gauss(820.0, 220.0), 300.0), 1),
        "solana_cu": int(rng.gauss(281000, 3500)),           # alt_bn128 groth16 verify
        "solana_fee_lamports": 5000 + int(abs(rng.gauss(90, 60))),
        "ts": iso(ts),
    }


def make_sessions(rng):
    sessions = []
    ts = BASE_TS - timedelta(hours=2)
    specs = [
        ("off", 572.0, 579.0, 0.0),
        ("off", 572.0, 579.0, 0.0),
        ("off", 572.0, 579.0, 0.0),
        ("snp", 536.0, 545.0, 2.4),
        ("snp", 536.0, 545.0, 2.4),
        ("snp", 536.0, 545.0, 2.4),
    ]
    for i, (mode, lo, hi, attest_s) in enumerate(specs, start=1):
        sessions.append({
            "session_id": f"sess-{mode}-{i:02d}",
            "sev_mode": mode,
            "boot_s": round(rng.uniform(34, 41) + (12 if mode == "snp" else 0), 1),
            "model_load_s": round(rng.uniform(4.2, 96.0), 1),   # bitnet ... 70b from NVMe
            "first_attestation_s": round(attest_s + (rng.uniform(0.2, 0.9) if mode == "snp" else 0.0), 2),
            "stream_triad_gbs": round(rng.uniform(lo, hi), 1),
            "kernel": "6.14.0-13-generic",
            "mitigations": "default (all on); smt=on",
            "ts": iso(ts + timedelta(minutes=9 * i)),
        })
    return sessions


def main():
    rng = random.Random(SEED)
    records = []
    ts = BASE_TS

    # Legs A/B core matrix: 2*4*4*3*2*3 = 576 cells * 3 kept samples = 1728
    for leg in ("A", "B"):
        for model in MODELS:
            for threads in THREADS:
                for pt in PROMPTS:
                    for ot in OUTPUTS:
                        for conc in CONCURRENCY:
                            for s in range(DISCARD_FIRST + 1, N_PER_CELL + 1):
                                records.append(make_ab_record(rng, ts, leg, model, threads, pt, ot, conc, s))
                                ts += timedelta(seconds=11)

    # Leg C: 2 paths * 3 prompts * 2 outputs * conc {1,8} * 8 kept = 192
    for path in ("C-direct", "C-proxied"):
        for pt in PROMPTS:
            for ot in OUTPUTS:
                for conc in (1, 8):
                    for s in range(DISCARD_FIRST + 1, DISCARD_FIRST + 9):
                        records.append(make_c_record(rng, ts, path, pt, ot, conc, s))
                        ts += timedelta(seconds=7)

    # Leg D: 3 rungs * {off, snp} * n=5 = 30
    for model in D_RUNGS:
        for sev_mode in ("off", "snp"):
            for s in range(1, 6):
                records.append(make_d_record(rng, ts, model, sev_mode, s))
                ts += timedelta(seconds=int(D_RUNGS[model]["prove_s"]) + 30)

    sessions = make_sessions(rng)

    req_path = HERE / "synthetic.jsonl"
    with req_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")

    sess_path = HERE / "synthetic_sessions.jsonl"
    with sess_path.open("w") as f:
        for s in sessions:
            f.write(json.dumps(s, separators=(",", ":")) + "\n")

    print(f"wrote {len(records)} request records -> {req_path}")
    print(f"wrote {len(sessions)} session records -> {sess_path}")


if __name__ == "__main__":
    main()
