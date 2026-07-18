# verified-inference

Measures what hardware-attested inference actually costs — latency, throughput,
dollars — versus identical unattested infrastructure, on a bare-metal AMD EPYC
Turin box (SEV family TEE) accessed through Sunburst. Full contract:
the frozen schemas, `models.yaml`, and the implementation itself. Operational
evidence lives in **[recon/findings.md](recon/findings.md)** and the independent
**[AUDIT.md](AUDIT.md)**. Unresolved work is tracked in
**[FIXES.md](FIXES.md)**.

## Headline result

**AMD SEV-ES memory-encryption tax = 26% on memory bandwidth** (STREAM triad,
identical 32-vCPU/64G VMs, only SEV state differs: 346 → 256 GB/s). In the newer
cloned-disk plain/SNP inference twin, median single-stream throughput tax is
**5.8% BitNet, 4.1% 8B Q4, 9.3% 8B Q8, and 7.3% 70B Q4** across four matched
thread/prompt cells per model. The report keeps the historical SEV-ES result
and the causal SNP matrix separate.

## What works today

- **TEE:** SEV + SEV-ES + SEV-SNP enabled on the box (host evidence in recon;
  kernel 6.17). SEV-ES CVMs measured for leg B; **SNP guests boot** (fresh-built
  AMDSEV OVMF fixed the `guest_memfd`/APIC gap) and the vinfer server runs
  INSIDE one: live `grade=snp`, report → VCEK → ASK → ARK verified to the AMD
  root, receipt on devnet — `vinfer verify runs/snp-receipt.json` is 11/11 PASS
  with zero skips (see `AUDIT.md`).
- **Serving:** all 5 `models.yaml` runtimes are live inside the public 832 GiB
  SNP guest: BitNet, 8B Q4, 8B Q8, 70B Q4, and GLM-5.2 Q4. The canonical
  surface is OpenAI-compatible streaming `POST /v1/chat/completions`; prices
  derive from warmup-filtered measured throughput.
- **Attestation:** binding v2 (registry hash), off-chain + in an Anchor program
  **live on Solana devnet**; `vinfer verify` checks the signed report and exact
  on-chain records. The SNP report hardware-binds the boot measurement, enclave
  key, and guest-declared registry digest. It does not independently prove which
  mutable userspace code or weights executed; closing that gap requires a
  measured immutable root/code chain. That dm-verity boot pipeline exists and
  is in isolated fail-closed testing; it has not replaced the public guest.
- **Prompt and response privacy:** the TEE console verifies the SNP report,
  AMD chain, policy, HPKE key binding, and devnet registry record before it
  encrypts. `POST /v1/chat_e2e` streams encrypted token chunks and seals the
  full response, metrics, and usage back to the browser. The public edge sees
  ciphertext and routing metadata, not chat text. Solana stores only fixed-size
  prompt, response, and model hashes plus receipt metadata.
- **Payments:** the active payment boundary is the official pay 0.22 gateway,
  generated from `models.yaml` with per-model token rates and `x402-upto` usage
  settlement. A real sandbox 402/payment/proxy cycle passes. No mainnet gateway
  or catalog entry is published yet (see Category B2 in `FIXES.md`).
- **External upstream:** Claude is the only external model API, used only by
  the measured direct/proxied Leg C path. All registry models run from local
  open weights.
- **Public endpoint:** `https://verified-inference.213.239.141.40.sslip.io` with
  a valid public TLS certificate. Generation requires an authenticated browser
  session or the pay gateway's bearer credential; models, attestation, and
  receipts remain free. Build `vinfer-0.8.0` is anchored at devnet PDA
  `7asixqGuMEbu4Dm89XRKJBMPaYPtCPjWLBGJxL7AX6h` with the complete five-model
  registry hash; all five guest runtimes are active.
- **Public console:** `https://console.213.239.141.40.sslip.io` serves the live
  measurement UI and report data from the same TLS host; its same-origin proxy
  reaches the SNP API. The operator-issued access code creates an HttpOnly test
  session; no payment or wallet is needed to test chat in the browser.
  `/measurements/` exposes all 1,244 unique frozen-schema request records and
  all session rows, alongside the aggregate charts. The no-TEE baseline, TEE
  models, and Claude proxy are live console routes. The zero-knowledge route is
  explicitly pending Sunburst GPUs.

## Quickstart (real only — there is no mock)

The server serves the actual models in `models.yaml` via `infra/run-servers.sh`;
it does not mock anything. Point the CLI/web at a running server (the box):

```bash
export VINFER_URL=https://verified-inference.213.239.141.40.sslip.io
export VINFER_AUTH_TOKEN="operator-issued-access-code"
uv run vinfer attest                          # real grade: none (bare metal) / launch-only (in CVM) / snp
uv run vinfer infer --model bitnet-2b --prompt 'hello' --e2e
uv run vinfer verify runs/snp-receipt.json    # 11/11 exact cryptographic/on-chain PASS
make pay-sandbox-test                         # official x402, ephemeral sandbox funds
make payskill                                 # generate + sync + validate; never publishes
make verify-registry                          # models.yaml integrity
make report                                   # curate raw runs + regenerate JSON/HTML
```

On the box, the measured runtimes plus `infra/run-vinfer-paid.sh` start the
authenticated SNP origin.

Add a model by placing and hashing the weights, adding one `models.yaml` entry,
then running `make bench MODEL=<id>`, `make pricing`, restarting the origin to
re-attest and update its registry record, and finally `make payskill`. Any
model-specific configuration outside `models.yaml` is a defect.

## Layout

`server/` (registry, runtimes, attest, crypto, receipts, x402) · `harness/`
(matrix runner, frozen `schema.json`) · `infra/` (SSH provisioning, QEMU/CVM
launch, sweep + measure scripts) · `solana/` (Anchor program + devnet notes) ·
`cli/` (`vinfer`) · `report/` (generator + pricing) · `zk/` (private-source
boundary; leg D is unmeasured) · `web/` (Next.js UI) · `payskill/` (generated).

## Rules that never bend

- Sunburst SSH key: path-only, never read/print/commit. No secrets in the repo.
- `models.yaml` is the only model config; prices + pay.sh listing are generated.
- Attestation grades are never faked (`none`/`launch-only`/`snp` mean what they
  say); `vinfer verify` prints SKIPPED rather than pretending.
