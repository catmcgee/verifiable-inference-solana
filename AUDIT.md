# AUDIT — verified-inference (independent audit, 2026-07-16)

> **POST-FIX STATUS (2026-07-16, after "fix the things in audit.md").** Category A
> was applied by the auditor. Category **B1, B2, B3 are now FIXED** — see
> `FIXES.md` "Category B — RESOLUTIONS": the report draws A/B from the matched
> cell (no fabricated numbers; honest ~2% decode tax, 26% STREAM), the on-chain
> grade enum is `NoTee` (no mock; demo re-registered honestly), and
> `vinfer verify runs/demo-receipt.json` is green (SNP row SKIPPED). B4/B5 remain
> gated on paid calls / B200s / an idle box. The findings below are the ORIGINAL
> snapshot and are kept verbatim for the record.

Auditor pass over the repo at HEAD `3d83357`. Evidence = file:line, live command
output, on-chain reads, commit hashes. SPEC (parent brief) is authoritative;
where README/PLAN/recon disagree with the box or with each other, that is a
finding. Mock removal is a DOCUMENTED, INTENTIONAL deviation (parent order
"real only") — not a defect; noted, not re-added.

## Executive summary

Counts across 34 checklist items: **PASS 20 · PARTIAL 6 · WRONG 3 · MISSING 3 · UNVERIFIABLE 2.**

Bluntest first — what is OVERCLAIMED:

1. **Report labels the measured TEE as "SEV-SNP" — it is SEV-ES.** Every leg-B
   record is `sev_mode=es` (grade launch-only; SNP guest never booted). Yet
   `report/generate.py` hardcodes "SEV-SNP" in 5 places (lines 376, 383, 409,
   524, 685); rendered `report/out/report-real.html` shows "SEV-SNP" 11×. The
   report's own honest-limits section (line 561) and `web/public/measurements.json`
   both correctly say SEV-ES. Self-contradiction; the charts overclaim. → FIXED (A).

2. **Report numbers are FABRICATED against the real data.** The curated leg-B
   set (`runs/*.jsonl`, 30 rows) was measured at `threads=32, prompt_tokens=16`
   only; the leg-A sweep is `threads∈{16,32,64,128}, prompt∈{128,1024,8192}`.
   They share NO cell. So the generator's A/B math divides by an empty leg-B
   median and emits: tax-curve = **100.0% at every point**, leg-B throughput =
   **0 tok/s**, break-even = **×0.00**, STREAM tile = **−27.2%** (it pools
   bare-metal 128t 357.1 with plain-VM 32t 346.19 as "off"). The real,
   repo-known finding (~2% flat SEV-ES inference tax) is ABSENT from the HTML.
   Verified by re-render. → Category B (needs re-point to `legAB-inference.jsonl`
   or a real leg-B sweep; do not ship the current render).

3. **On-chain attestation grade decode is inverted → mock reads back as "snp".**
   `cli/devnet.py:71` maps `{0:"none",1:"launch-only",2:"snp"}`, but the Anchor
   enum order is `Snp=0, LaunchOnly=1, Mock=2` (`state.rs:7-14`). The devnet demo
   registered `{ mock: {} }` (`scripts/devnet-demo.ts:146`). LIVE PROOF:
   `vinfer verify runs/_scratch/devnet-receipt.json` prints
   `registry PDA … grade=snp` for a MOCK record. → FIXED (A).

## Box reality (read-only, `ssh sunburst`, load 0.13, 2 users, no heavy run)

kernel `6.17.0-40-generic`; flags `sev sev_es sev_snp`; `/dev/sev` present;
`/dev/sev-guest` absent (host, not guest); `kvm_amd/parameters/sev_snp=Y`.
So SEV+SEV-ES+SNP are enabled at the HOST; SNP *guest* boot is what's blocked
(README: guest_memfd/APIC gap). This makes `recon/findings.md` stale/WRONG.

## Evidence table

| # | Checklist item | Status | Evidence |
|---|---|---|---|
| 1 | Recon gate findings.md real + decision row | WRONG | `recon/findings.md:9` "SEV disabled in BIOS", `:26-34` kernel 6.8 "SNP blocked on kernel" — box is kernel 6.17, `sev_snp=Y`, SEV+ES live. STREAM SEV-on absent from findings.md (lives in LEDGER + `runs/legAB-stream.jsonl`). → FIXED (A) |
| 2 | Honest grade if plain SEV (no overclaim) | PASS(server)/WRONG(report) | server: `attest/report.py:35-45` es→launch-only, live `/v1/attestation` grade `none`. report overclaims SNP (finding #1) |
| 3 | Leg A serving, real, measured | PASS | live infer 134 tok/s bitnet; `runs/legA-full.jsonl` 320 rows |
| 4 | Leg B (SEV CVM, attest binds key+weights) | PARTIAL | SEV-ES only, grade launch-only, no signed runtime report; 30 rows one cell |
| 5 | Leg C (attested proxy, Anthropic plaintext, honest) | PARTIAL | `runs/legC-probe.jsonl` 6 recorded rows (C-direct); C-proxied MISSING; honesty stated report+frontend |
| 6 | Leg D zkML ladder | MISSING | deferred (LEDGER); `verify_inference_proof` is a documented stub (`lib.rs:72`, `state.rs:95`) |
| 7 | Registry single source of truth | PASS | `models.yaml`; no 2nd config (grep clean); `make verify-registry` hash `49dc89aa…` == live server |
| 8 | Runtime adapter interface | PASS | `server/runtimes/{base,llamacpp,bitnetcpp}.py` |
| 9 | Endpoint surface fixed; /v1/infer thin alias | PASS | `main.py:197,233`; `/v1/models|attestation|receipts` free |
| 10 | pricing.py derives prices; not hand-written | PASS | `report/pricing.py`; `pricing-config.yaml`; models.yaml comment enforces |
| 11 | x402 upfront quote + no-refund documented | PASS | `x402/middleware.py`, `DESIGN.md`; free unless `VINFER_X402=1`; tests green |
| 12 | pay.sh listing generated, not published pre-deploy | PASS | `payskill/generate_listing.py`; states receipt+grade (`generated/…md:4`); publish P5-gated |
| 13 | Binding v2 REPORT_DATA=hash(pubkey‖registry_hash‖build) | PASS | `attest/report.py:56`, `attest_verify.py:37`; registry_hash sorted pairs |
| 14 | PDA carries binding_version; v1 not reinterpreted; verify prints which | PASS | `state.rs:34`, `vinfer.py:154-165` prints v1/v2 |
| 15 | Schema frozen v1, no silent fork | PASS | `harness/schema.json` single commit `7f73259`; migrate rule intact |
| 16 | Per-session schema | PASS | `session_schema.json` has boot_s/model_load_s/first_attestation_s/stream_triad_gbs/kernel/mitigations |
| 17 | Matrix breadth | PARTIAL | leg A sweep full; leg B 1 cell×3 models; hpke/conc/prompt grid for B, C-proxied, D MISSING |
| 18 | Solana register_attestation | PASS | `instructions/register_attestation.rs`; devnet CU 10,171 |
| 19 | post_receipt ed25519 via introspection, NOT naive | PASS | `ed25519.rs` strict: preceding ix, 1 sig, no cross-ix ref, pubkey+msg match |
| 20 | Merkle-batched receipts | PASS | `post_receipt_batch.rs`; ~465 CU/receipt batched |
| 21 | verify_inference_proof Groth16 via alt_bn128 | MISSING | documented stub, `verified=false` until wired |
| 22 | On-chain = hashes only (privacy) | PASS | `state.rs` ReceiptAccount = prompt_hash/response_hash/model_hash only |
| 23 | vinfer verify full chain runs; failure understood | PARTIAL | live: binding+sig+registry-PDA+receipt-PDA real; SNP→KDS SKIPPED (no report); full-green not achievable vs demo (dummy zero-sig receipt + ephemeral server key). Grade decode bug (#3) |
| 24 | HPKE key in-CVM at boot, never persisted; attestation-gated | PASS | `crypto/hpke_box.py`, `session_box.py`; `attest_verify.py` refuses unless trusted; wire is ciphertext-only; `main.py:157` seals both directions |
| 25 | Client verifies SNP binding BEFORE encrypting | PASS | `vinfer.py:53-61` verify then send |
| 26 | Logging discipline — no plaintext prompt/response | PASS | grep: no logger/print of prompt/response/ciphertext in server/ |
| 27 | Secrets scan full history | PASS | `git log --all -p` grep: no OPENSSH/sk-ant/BEGIN/keypair; `.env.local` untracked; deployer keypair gitignored+untracked |
| 28 | .gitignore predates secret-shaped files | PASS | `7f73259` gitignore-before-secrets |
| 29 | SSH key path-only, never inlined/copied | PASS | `infra/ssh_config` host/user only; IdentityFile only in comment example; PLAN/LEDGER path-only |
| 30 | Leg C honesty (Anthropic sees plaintext, not verified) | PASS | report `section_leg_c` + `web/lib/labels.ts:65` |
| 31 | Tachyon containment (no vendor/mirror/quote) | PASS | `.gitignore:29-31`; `zk/TACHYON-NOTES.md` reference only |
| 32 | TLS external only | UNVERIFIABLE | deploy-gated (no public host yet); stated intent |
| 33 | CLI vinfer infer/attest/verify/bench/receipts/pay | PASS | all exercised; live infer+verify green (honest skips) |
| 34 | Web deadpan, grade+scope honest, leg D labeled deferred | PASS | `MeasurementPanel.tsx`, `labels.ts` (hashes only, no plaintext, D disabled) |

UNVERIFIABLE: (32) TLS — no public deploy; and full SNP attestation path — no
SNP guest exists yet (both are honest gaps, not defects).

## Intentional deviation (documented per parent order)

"Remove ALL mock — real only." `server/mock_backend.py`, synthetic fixtures,
`gen_synthetic.py`, mock matrix DELETED (commit `3d83357`); backend hardwired
real (`main.py:30`). Pass-2 harness/report/verify tested against the REAL server
(`127.0.0.1:8477`) and real `runs/*.jsonl`, NOT re-added mock. Residue of the
deviation, NOT re-fixed by re-adding mock: on-chain enum `AttestationGrade::Mock`
still exists in the DEPLOYED program (`state.rs:13`) and the devnet demo used it
— see FIXES.md Category B (deployed-schema change).
