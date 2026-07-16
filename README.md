# verified-inference

Measures what hardware-attested inference actually costs — latency, throughput,
dollars — versus identical unattested infrastructure, on a bare-metal AMD EPYC
Turin box (SEV family TEE) accessed through Sunburst. Full contract:
**[PLAN.md](PLAN.md)** + **[ADDON-REGISTRY.md](ADDON-REGISTRY.md)**. Running
log: **[LEDGER.md](LEDGER.md)**.

## Headline result

**AMD SEV-ES memory-encryption tax = 26% on memory bandwidth** (STREAM triad,
identical 32-vCPU/64G VMs, only SEV state differs: 346 → 256 GB/s). Because CPU
LLM inference is memory-bandwidth-bound — throughput peaks at 32–64 threads and
regresses at 128 (the bandwidth wall) — this 26% is the ceiling the per-model
inference tax climbs toward as models get larger. That is the thesis, measured.

## What works today

- **TEE:** SEV + SEV-ES + SEV-SNP enabled on the box (BIOS recipe in LEDGER;
  kernel 6.17). SEV-ES confidential VMs boot and are verified. (SNP *guest* boot
  hits an upstream `guest_memfd`/APIC gap — documented; SEV-ES used for leg B.)
- **Serving:** 5 models via a model registry (`models.yaml`) — BitNet b1.58-2B,
  Llama-3.1-8B Q4/Q8, Llama-3.3-70B Q4, GLM-5.2 (744B MoE). OpenAI-compatible
  `POST /v1/chat/completions`; prices derived from measured throughput.
- **Attestation:** binding v2 (registry hash), off-chain + in an Anchor program
  **live on Solana devnet**; `vinfer verify` checks the on-chain records.
- **Input privacy:** HPKE encrypt-to-enclave (`/v1/infer_sealed`), ~0.37ms tax.
- **Payments:** token-metered design on the Solana session-intent spec
  (`server/x402/DESIGN.md`), P5.

## Quickstart (local, mock backend)

```bash
uv sync
uv run uvicorn server.main:app --port 8477      # terminal 1
uv run vinfer attest                            # terminal 2
uv run vinfer infer --model bitnet-2b --prompt hello --receipt-out /tmp/r.json
uv run vinfer verify /tmp/r.json                # PASS/FAIL/SKIPPED per step (checks devnet)
uv run make verify-registry                     # models.yaml integrity
uv run python report/generate.py                # HTML from synthetic fixtures
```

Real backend on the box: `VINFER_BACKEND=llama` with llama-servers from
`infra/run-servers.sh`. Add a model: see the checklist in ADDON-REGISTRY.md
(`make bench MODEL=<id>` → `make pricing` → re-attest → `make payskill`).

## Layout

`server/` (registry, runtimes, attest, crypto, receipts, x402) · `harness/`
(matrix runner, frozen `schema.json`) · `infra/` (SSH provisioning, QEMU/CVM
launch, sweep + measure scripts) · `solana/` (Anchor program + devnet notes) ·
`cli/` (`vinfer`) · `report/` (generator + pricing) · `zk/` (leg-D notes;
tachyon deferred to B200s) · `web/` (Next.js UI) · `payskill/` (generated).

## Rules that never bend

- Sunburst SSH key: path-only, never read/print/commit. No secrets in the repo.
- `models.yaml` is the only model config; prices + pay.sh listing are generated.
- Attestation grades are never faked (`mock`/`launch-only`/`snp` mean what they
  say); `vinfer verify` prints SKIPPED rather than pretending.
