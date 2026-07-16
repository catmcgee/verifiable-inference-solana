# verified-inference

Measures what hardware-attested inference actually costs — latency, throughput,
dollars — versus identical unattested infrastructure, on a bare-metal AMD EPYC
Turin box (SEV-SNP) accessed through Sunburst. Full contract: **[PLAN.md](PLAN.md)**.
Running log: **[LEDGER.md](LEDGER.md)**.

## Status: P0 (local scaffold, mock backends)

```bash
uv sync

# terminal 1 — mock server (bitnet.cpp/llama.cpp land in P2)
uv run uvicorn server.main:app --port 8477

# terminal 2 — the CLI
uv run vinfer attest
uv run vinfer infer --model bitnet-2b --prompt "hello" --receipt-out /tmp/r.json
uv run vinfer verify /tmp/r.json           # PASS/FAIL/SKIPPED per pipeline step
uv run vinfer bench --matrix harness/matrix.mock.json --out runs/_scratch/run.jsonl

# report from synthetic fixtures
uv run python report/generate.py
```

Measurement schema is frozen at `harness/schema.json` (v1) — changes migrate
old JSONL, never fork it.

## Layout

See PLAN.md § Repo layout. Notable: `zk/TACHYON-NOTES.md` (leg D prover audit),
`recon/run_recon.sh` (P1 recon gate, runs once `Host sunburst` exists in
`~/.ssh/config`), `solana/` (attestation registry + receipts, Anchor).

## Rules that never bend

- The Sunburst SSH key is referenced by path only; no secrets in this repo, ever.
- Attestation grades are never faked: `mock` / `launch-only` / `snp` mean what
  they say, and `vinfer verify` prints SKIPPED rather than pretending.
