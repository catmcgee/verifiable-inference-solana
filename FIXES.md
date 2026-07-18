# Audit Fixes and Plans

## Category A: Applied

Each safe fix was committed separately.

| Commit | Fix | Verification |
|---|---|---|
| `01f29db` | Updated stale Anchor test fixtures from removed `mock` grade to `noTee`. | Localnet tests PASS. |
| `309aa2e` | Changed browser copy to server-reported SNP, added "not performed in browser", and labeled leg D as unmeasured/stub/integrity-only. | Normal + static Next builds PASS; deployed chunk checked. |
| `8133f88` | Corrected input-only HPKE wording, removed unsupported GPU numbers, added honest empty-leg-D and empty-chart behavior. | Real + sparse synthetic report renders PASS. |
| `8b5d173` | Added tracked TLS proxy config with access logging disabled. | Caddy validated/reloaded; log sizes unchanged after new requests. |
| `02434c5` | Removed private-upstream implementation details from public docs and corrected B200 deferral claims. | Rewritten history contains neither the removed notes nor the private URL. |
| `46e01e4` | Replaced interactive `next lint` setup with a real noninteractive ESLint job. | `npm run lint` PASS. |
| `de23935` | Pinned patched PostCSS 8.5.19. | `npm audit --audit-level=moderate`: 0 vulnerabilities. |

Generated/deployed follow-through:

- Regenerated `report/out/report.html` from 952 retained requests + 4 sessions.
- Built static web output with the production API URL and overlaid it on
  `/srv/vinfer-web`; no service/guest restart.
- Reloaded Caddy after validation. Existing access-log files were not deleted.
- Tightened ignored `.env.local` from mode 0644 to 0600. This local-only mode
  change cannot be represented by a repository commit.

## 2026-07-18: Browser Privacy and Full Receipt Chain

- Added a browser HPKE client using X25519/HKDF-SHA256/ChaCha20-Poly1305. The
  TEE route refuses to send until the browser verifies AMD KDS, local policy,
  the signed HPKE key, and the devnet attestation PDA.
- `/v1/chat_e2e` now accepts encrypted chat history, streams individually
  encrypted token chunks, and seals the complete response, metrics, and usage.
  The raw-prompt CLI path remains compatible and now reports real token usage.
- The browser recomputes canonical request-v2 and response hashes before it
  accepts the signed receipt. It then verifies the receipt signature and exact
  receipt PDA content directly against Solana devnet.
- Added Python endpoint/privacy tests plus a real cross-language test that runs
  `web/lib/e2e.ts` under Node against the Python enclave session. The live
  Playwright test confirms its unique prompt is absent from the request body.
- Deployed `vinfer-0.8.0`, independently verified its SNP/KDS/policy binding,
  and registered PDA `7asixqGuMEbu4Dm89XRKJBMPaYPtCPjWLBGJxL7AX6h`.
  A sealed request posted receipt index 0; full `vinfer verify` returned OK.
- Updated the console privacy/execution panel and documentation. The site now
  distinguishes sealed TEE inference from the TLS-only baseline/Claude paths
  and states that the loaded browser bundle remains part of the trust base.
- The deployed measurements view now contains 1,244 unique request rows plus
  four session rows.
- Added and deployed a responsive request-path diagram explaining Caddy, the
  loopback-only guest forward, browser-to-TEE privacy, operator-only SSH, and
  hash-only Solana receipts. Desktop hover/focus and mobile layout checks pass.
- Rewrote local Git history, as explicitly authorized, to remove obsolete
  operational ledgers, plans, add-on notes, and private-upstream notes from all
  reachable commits. Post-rewrite Gitleaks found zero leaks;
  history searches found zero private-URL, SSH-fingerprint, or removed-path
  commits. No remote was configured, so there was nothing to force-push.

## Post-Audit Remediation: Authenticated Testing and x402 Layer

Applied on 2026-07-17:

These changes began in a pre-existing dirty worktree. They were tested and later
captured in the consolidated runtime and web commits without reverting unrelated
work.

- Added a fail-closed origin auth layer with bearer access for the pay gateway
  and signed, expiring Secure/HttpOnly/SameSite browser sessions.
- Added the console sign-in/sign-out flow without embedding or persisting the
  access code. The ignored code file is mode 0600.
- Removed the legacy payment gate from every active inference path. The old
  channel code remains only as devnet experiment evidence.
- Added `models.yaml` -> pay runtime YAML -> provider sync -> PAY/OpenAPI ->
  catalog validation generation.
- Added `make pay-sandbox-test`; the real pay 0.22 sandbox flow passes from 402
  challenge through payment, bearer injection, usage observation, and receipt.
- Deployed the authenticated `vinfer-0.6.0` origin and static console. A live
  login/completion/logout test passed with grade SNP.
- Registered the new binding on devnet at
  `6wYN1DsGUmxG4Ar98wcLxShbCGUiSoYFQWcpaR8zjmUV` (transaction
  `5YRrGUexD7wf5GUmkvsGPGRjqfcBqpuK4irsysrU7Sb27XXvXFxJXUW7Mr8LGuthmeH5mjt7kkubVrDdH22h3mzz`).
- Replaced the duplicated model launcher with a `models.yaml` consumer and
  conformed adapters to `load/tokenize/stream_generate`.
- Corrected binding v2 to hash all five hash-bearing registry entries. The
  final 832 GiB guest publishes all five healthy runtimes as `active_models`.
- Added the GLM open-weight baseline and explicit missing-SNP comparison to the
  report, then made GLM live inside the larger SNP guest. The matched GLM SNP
  experiment remains unrun. Claude remains the only external model API.
- Fixed the static `/measurements/` route and exposed all 1,198 raw requests
  plus four session records with filters, warmup labels, and pagination.
- Made A/C/D real in-place scope selectors and Measurements the explicit data
  route, added leg/run/session filters, and verified desktop/mobile hit targets
  against the deployed console.
- Deployed `vinfer-0.7.0`: empty/EOS completions no longer become 500s, exact
  llama.cpp usage is mandatory, streaming chunk counts are not mistaken for
  token counts, and finish reasons are preserved. Eight JSON and one SSE live
  completions passed; one empty completion exercised the repaired path.
- Added an explicit `onchain_status=not-posted` and the registered boot
  attestation PDA to signed receipts. The UI no longer suggests that this is a
  confirmed per-inference receipt transaction.
- Registered build 0.7 at devnet PDA
  `7pi7ytu6KRpdyZ9gHgoAQqPCx3124d5UwEoo9obmwkBq` (transaction
  `4p6AP7rGCqKYyY5Bc28m4P9bb6BN9LrEM1YNBhY4HdbLuPgbsxX68uQjVeHqwVPVHAbMLVPcf5y6spMrqjmGkVia`).
- Linked every report chart's contributing run IDs into the browser and
  changed absent receipt post/confirm/CU/fee measurements from numeric zero to
  `not recorded`.
- Added a registry-driven JSONL migration and filled 2,360 legacy empty
  `quant` values across eight raw/curated artifacts. All 2,772 request records
  validate and the public 1,198-row dataset now has no empty quantization.
- Built and registry-verified a 500 GiB GLM model image, launched an independent
  832 GiB/64-vCPU SNP guest, verified its report through AMD KDS, and moved the
  public Caddy upstream only after all five models, auth, JSON, and SSE passed.
- Disabled GLM's reasoning-only chat template mode on the portable OpenAI
  surface and fixed live throughput to use llama.cpp token-level timings.
  Final GLM checks return visible content at 13-16 tok/s instead of `0.0`.
- Registered the final boot at devnet PDA
  `GbJUCjVMnzFe85hkvuoeGsG5NZXWDH7G8kT1p9bfGDg5`; live pay registry validation
  and the x402 sandbox cycle both pass. Nothing was published.

The paid gateway was not exposed publicly and no provider artifact was
published. Those steps require intentional mainnet wallet configuration.

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

### B2: Finish payment productionization

Completed: official pay/x402 integration, generated runtime and provider
pipeline, origin credential injection, response usage metering, no-probe
catalog validation, and a real sandbox payment cycle.

Remaining:

1. Resolve the contract mismatch: pay 0.22 `x402-upto` refunds the unused
   ceiling, while the original specification requires prompt-plus-max-output
   charging with no refund.
2. Configure a mainnet operator/recipient wallet and stable paid HTTPS hostname.
3. Regenerate with `network: mainnet`, then run strict live catalog probes.
4. Do not publish or PR until all listing claims are true.

The five-model live-registry check now passes against the correctly sized SNP
guest. Publication remains blocked by the mainnet, paid-hostname, live-probe,
and per-inference receipt-posting requirements above.

### B3: Finish measured-build attestation

1. Cut the tested measured-boot/dm-verity pipeline over to the public all-model
   guest before claiming the public report proves executed userspace or weights.
   The isolated BitNet guest already passes the immutable manifest verifier.
2. Preserve v1 interpretation; any PDA/account migration needs an explicit
   deployed-program plan.

### B4: Finish Solana proof verification and economics

1. Replace the proof stub with Groth16 verification using Solana alt_bn128
   syscalls and the required lineage; accept actual proof/public inputs.
2. Add negative proof tests, verifier-key binding, and public model/input hash
   binding before setting `verified=true`.
3. Measure CU/rent/fees and report base/p50/p90 priority-fee projections,
   $/receipt and $/1M receipts, single vs batch.

### B5: Finish client/report deliverables

1. Add the missing matched GLM SNP/MoE-vs-dense run, full receipt economics,
   zkML ladder, and Groth16-vs-signed-hash comparison to the report.

### B6: Make add-a-model genuinely one-file and testable

The launcher, n>=10 pricing bench, runtime YAML, provider sync, and validator
now consume the registry. Create a tiny real model fixture/runtime and automate
the remaining restart/re-attest/local-PDA steps against temporary state. The
only user edit should be the registry entry; do not point this test at the
public paid service.

### B7: Existing access-log retention

New Caddy access logging is disabled. Existing files still contain client IP
and User-Agent metadata. Deletion was prohibited during the box audit. Decide a
retention/deletion policy before production use.
