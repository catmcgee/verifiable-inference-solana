# FIXES — verified-inference audit

## Category A — applied (one commit each, on `main`)

| Commit | Fix | Why safe |
|---|---|---|
| `226b518` | `cli/devnet.py` on-chain grade decode `{0:snp,1:launch-only,2:mock}` (was `{0:none,1:launch-only,2:snp}`) | client-side read decode only; not deployed schema. Verified live: demo Mock PDA now reads `mock`, previously read `snp` |
| `8028c37` | `report/generate.py` label measured TEE **SEV-ES** not SEV-SNP (5 spots) | pure label correction to match the data (`sev_mode=es`); generator output is gitignored/regenerated |
| `210a959` | `recon/findings.md` current-state banner: kernel 6.17, SEV+ES+SNP host-enabled, leg B = SEV-ES/launch-only, STREAM both states | doc-only; "box wins over docs" per PLAN; stale text kept for history |
| `b0f89d5` | `.gitignore` drop stale "synthetic fixtures ARE committed" comment | comment-only; reflects mock-removal deviation |

Not applied as Category A (would be gold-plating / risk): rewriting the report's
A/B numeric aggregation — see B1. It is the correct home for the real fix, but a
safe mechanical edit can't produce honest numbers from mismatched inputs.

## Category B — flag + written plan (DO NOT touch without owner sign-off)

### B1 — Report A/B numbers are fabricated (grid mismatch). HIGHEST PRIORITY.
`report/generate.py` computes tax/throughput/cost/break-even on a grid
(`threads=64`, `prompt∈{128,1024,8192}`) that the curated leg-B data
(`threads=32, prompt=16`, 30 rows) never hits. Empty leg-B medians → tax-curve
100% everywhere, leg-B tok/s = 0, break-even ×0.00, STREAM tile −27.2% (pools
bare-metal 128t with plain-VM 32t). The real ~2%-flat SEV-ES inference finding
(LEDGER session 7; `web/public/measurements.json`) never appears in the HTML.
**Plan:** (a) point `section_tps_ab` / `tax_by_model_threads` / `section_cost` /
`section_breakeven` at `runs/legAB-inference.jsonl`, where A and B are matched at
the SAME cell (`threads=32, prompt=16`) → yields the honest ~2%; (b) add a guard
so any unmatched cell renders `n/a`, never a ratio against 0; (c) `section_stream`
must compare plain-VM (346.19) vs SEV-ES (256.10) = 26.0%, and NOT pool the
bare-metal 128t anchor into the "off" median; (d) drop/soften the "tax grows
toward 26%" narrative — the measured result contradicts it. No paid/long run
needed (data exists). A full thread/prompt A/B grid for leg B would need a box
sweep (long) and is optional. Until done, **do not publish the render.**

### B2 — `AttestationGrade::Mock` still in the DEPLOYED Anchor program.
After the "remove ALL mock" order, `state.rs:13` still defines `Mock`, and the
live devnet demo (`scripts/devnet-demo.ts:146`) registered with it — so the demo
PDA on devnet is grade `mock`. Touches deployed on-chain schema.
**Plan:** decide with owner — (a) keep the enum variant (harmless; new boots
register `snp`/`launch-only`) but re-run `devnet-demo.ts` to register the demo
enclave as `launch-only` for an honest demo record, OR (b) program upgrade that
removes `Mock` + re-deploy + re-register. (a) is cheaper and non-breaking.

### B3 — `vinfer verify` cannot go fully green against the devnet demo.
The committed demo receipt (`runs/_scratch/devnet-receipt.json`) has a zero
signature and a different enclave key than the (ephemeral, per-boot) live server
key, so binding + sig + registry-hash steps FAIL by construction; only the PDA
lookups pass. The SNP→KDS step is honestly SKIPPED (no SNP guest).
**Plan:** on a persistent server key, run `register_attestation` + `post_receipt`
for a REAL signed receipt on devnet, ship that receipt as the demo, so `vinfer
verify <receipt>` is green end-to-end except the SNP row (which stays SKIPPED
until an SNP guest boots and `cli/kds.py` runs for real). Devnet writes only.

### B4 — Missing legs/matrix cells (no code fix; data/hardware/paid).
Leg C-proxied (attested-proxy path), leg D ladder (all rungs), and the leg-B
HPKE/concurrency/prompt/thread grid are absent. Leg C needs paid Anthropic
calls (do NOT run during audit — use the 6 recorded `legC-probe` rows). Leg D is
deferred to B200s (owner decision, LEDGER) and its on-chain Groth16
(`verify_inference_proof`) is a documented stub. Flag only.

### B5 — Add-a-model end-to-end (ADDON checklist) not verified live.
The local tooling works (`make verify-registry` green; registry_hash matches the
running server; `pricing.py`/`generate_listing.py` are single-source off
`models.yaml`). A true end-to-end dummy-model run needs a weights file written to
the box NVMe + a server reload + re-attest + PDA update — which would perturb the
REAL running server (127.0.0.1:8477) and race the concurrent SNP-boot agent.
Blocker documented per instruction (no mock re-added). **Plan:** run the checklist
with a tiny real gguf during a maintenance window when the box is idle.
