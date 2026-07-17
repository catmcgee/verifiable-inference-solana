# Audit Fixes and Plans

## Category A: Applied

Each safe fix was committed separately.

| Commit | Fix | Verification |
|---|---|---|
| `16a7b52` | Updated stale Anchor test fixtures from removed `mock` grade to `noTee`. | Localnet 14/14 PASS. |
| `ba2447f` | Changed browser copy to server-reported SNP, added "not performed in browser", and labeled leg D as unmeasured/stub/integrity-only. | Normal + static Next builds PASS; deployed chunk checked. |
| `999bd30` | Corrected input-only HPKE wording, removed unsupported GPU numbers, added honest empty-leg-D and empty-chart behavior. | Real + sparse synthetic report renders PASS. |
| `eb77370` | Added tracked TLS proxy config with access logging disabled. | Caddy validated/reloaded; log sizes unchanged after new requests. |
| `62f2031` | Removed private-upstream implementation details from current public docs and corrected B200 deferral claims. | HEAD grep clean for the leaked internal terms; history caveat below. |
| `715336c` | Replaced interactive `next lint` setup with a real noninteractive ESLint job. | `npm run lint` PASS. |
| `0ccf621` | Pinned patched PostCSS 8.5.19. | `npm audit --audit-level=moderate`: 0 vulnerabilities. |

Generated/deployed follow-through:

- Regenerated `report/out/report.html` from 952 retained requests + 4 sessions.
- Built static web output with the production API URL and overlaid it on
  `/srv/vinfer-web`; no service/guest restart.
- Reloaded Caddy after validation. Existing access-log files were not deleted.

## Category B: Flag Only

These touch deployed schemas, attestation binding, pricing/payment behavior,
endpoint shape, or require paid/long experiments.

### B1: Complete the experiment, starting with the thesis gaps

1. Run memory latency and a truly matched off/SNP STREAM pair.
2. Run the full A/B Cartesian matrix, including GLM, 8192 prompts, 1024 output,
   64/128 threads, concurrency 1/4/8, and every CVM HPKE cell, n>=10.
3. Run the complete Claude direct/proxied grid with n>=10.
4. Run leg-D rungs 1-3 on the CPU box, n=5 each; attempt rung 4 only if rung 3
   projects below a few hours.
5. Do not retrofit invented values into existing JSONL. Append/migrate under the
   frozen schema and retain two raw warmups per cell.

### B2: Replace the payment prototype before listing

1. Implement the required x402/pay.sh-compatible mechanism.
2. Charge `prompt_tokens*in + max_tokens*out` upfront with documented no-refund
   behavior; remove local reconciliation/refund semantics.
3. Integrate posting/confirmation so every paid response can truthfully expose
   an on-chain receipt transaction ID and attestation grade.
4. Generate runtime YAML from `models.yaml`, then run `pay skills provider sync`
   and strict live validation. The current YAML is stale and invalid.
5. Do not publish or PR until mainnet settlement, stable production hostname,
   live probes, and all listing claims are true.

### B3: Resolve registry and attestation semantics deliberately

1. Remove hard-coded model paths/ports from `infra/run-servers.sh`; generate
   launch config from `models.yaml`.
2. Conform adapters to `load/tokenize/stream_generate` without changing the
   public response contract.
3. Decide and version whether v2 binds all registry entries or only healthy
   active runtimes. Current local and live hashes differ.
4. Build an immutable measured root/code/weight manifest before claiming the
   SNP report proves executed userspace or weights.
5. Preserve v1 interpretation; any PDA/account migration needs an explicit
   deployed-program plan.

### B4: Finish Solana proof verification and economics

1. Replace the proof stub with Groth16 verification using Solana alt_bn128
   syscalls and the required lineage; accept actual proof/public inputs.
2. Add negative proof tests, verifier-key binding, and public model/input hash
   binding before setting `verified=true`.
3. Measure CU/rent/fees and report base/p50/p90 priority-fee projections,
   $/receipt and $/1M receipts, single vs batch.

### B5: Finish client/report deliverables

1. Implement browser verification of SNP report, AMD chain/policy, HPKE binding,
   registry PDA, receipt signature, and exact on-chain record; render PASS/FAIL
   plus grade from that verdict, not the server JSON.
2. Return/persist receipt transaction metadata and link the actual transaction.
3. Add GLM/Z.ai reference, MoE-vs-dense, full receipt economics, zkML ladder,
   Groth16-vs-signed-hash, and complete run-ID links to the report.
4. Exclude missing/zero timing phases from cost aggregates or label them absent.

### B6: Make add-a-model genuinely one-file and testable

Create a tiny real model fixture/runtime usable only in integration tests, then
automate: hash -> temporary registry entry -> bench n>=10 -> pricing to temporary
registry -> restart/re-attest -> local PDA update -> runtime YAML -> provider
sync -> validator. The only user edit should be the registry entry. Do not point
this test at the public paid service.

### B7: Private-history decision

Commit `62f2031` removes private Tachyon implementation notes from HEAD, but old
Git objects remain. Before making the repository public, the owner must decide
whether to rewrite history and rotate published commit references. This audit
did not rewrite or force-push history.

### B8: Existing access-log retention

New Caddy access logging is disabled. Existing files still contain client IP
and User-Agent metadata. Deletion was prohibited during the box audit. Decide a
retention/deletion policy before production use.
