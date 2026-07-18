# Independent Audit: verified-inference

Audit date: 2026-07-18. The user's audit brief is the authoritative specification.
Repository plans, READMEs, prior audit claims, and prior-agent conversation notes
were treated only as evidence.

## Executive Summary

This is a real SNP/devnet prototype, not a specification-complete verified
inference service.

Bluntest findings first:

1. **The public guest still does not prove which userspace code or weights
   executed.** Its 832 GiB mutable root is honestly labeled `guest-declared`.
   An isolated dm-verity measured-boot guest passes the immutable-manifest
   verifier for BitNet, but it has not replaced the public all-model guest.
2. **The flagship TEE measurement is incomplete.** GLM-5.2 is served from
   the live 832 GiB SNP guest, but the required GLM SNP benchmark matrix and
   matched MoE-vs-dense experiment have not been run. Live serving is not a
   substitute for those measurements.
3. **The browser privacy and verification chain is now real.** The TEE route
   verifies AMD KDS, local policy, HPKE binding, and the attestation PDA before
   sending; prompt history and streamed output cross the edge only as
   ciphertext. It recomputes request/response hashes and verifies the signed,
   confirmed receipt PDA. A live Playwright canary passed. The loaded web
   bundle remains trusted client code and routing metadata remains visible.
4. **Payment remediation is real but not production-complete.** The live origin
   now uses authenticated browser sessions/bearer access instead of the
   experimental payment gate. A generated official pay 0.22 `x402-upto`
   gateway passes an end-to-end sandbox payment, but it is not deployed on
   mainnet and refunds the unused ceiling, contrary to the original no-refund
   requirement. The live origin posts receipts, but the public pay gateway and
   provider listing remain intentionally undeployed.
5. **The required experiment matrix was not run.** Current useful data covers
   four local models, prompts 128/1024, output 128, guest threads 16/32, and a
   narrow HPKE slice. Prompt 8192, output 1024, guest threads 64/128, full HPKE,
   GLM-in-SNP, memory latency, and all leg-D rungs are absent.
6. **Leg D is intentionally deferred.** The proof instruction remains an
   explicit non-verifying stub; no ZK inference result is claimed.
7. **Both current live chains pass.** `vinfer-0.8.2` open-model and
   `vinfer-legc-proxy-0.2.2` Claude-proxy receipts passed the SNP report,
   VCEK/ASK/ARK chain, v2 binding, registry PDA, receipt signature, receipt PDA
   derivation, and exact on-chain content with no skips.
8. **TLS is live and AWS is not used.** Caddy is the TLS reverse proxy on the
   Sunburst host; HTTP redirects to HTTPS and upstream listeners are loopback.
   No AWS SDK, service, credential, deployment, or account use was found.
9. **No secret value was found in Git.** Gitleaks over full rewritten history
    returned zero findings. A full directory scan found the expected ignored
    `.env.local` Anthropic credential plus six generated `.next/` cache false
    positives; neither is tracked. The local env file was tightened from mode
    0644 to 0600 during the audit without reading or printing its value. The
    authorized history rewrite removed obsolete operational prose, the private
    repository URL, and SSH fingerprints from all reachable commits.

### Post-audit remediation (2026-07-17)

Further remediation on 2026-07-18:

- Separated the human browser code from the strong gateway bearer. The three
  live routes accept the mode-0600 browser code, reject an incorrect code, and
  still accept the unchanged internal bearer as `gateway`. Fresh 0.8.2/0.2.2
  attestations and receipts were registered and fully verified on devnet.
- Deployed `vinfer-0.8.1` and `vinfer-legc-proxy-0.2.1`, registered both boot
  keys on devnet, and verified fresh confirmed receipts end to end. The Claude
  canary returned the requested text while explicitly reporting that Anthropic
  saw plaintext and its inference was not verified.
- Added typed request caps, a bounded in-memory receipt cache, and a 1 MB Caddy
  body limit. Public oversized requests return 413 before inference.
- Replaced hard-coded Solana browser figures with a structured, network-labeled
  measurement artifact; localnet batch cost is no longer labeled as devnet.
- Added a deterministic `make check` CI gate and public Playwright coverage for
  ciphertext-only TEE traffic and route-change history clearing.
- The published BitNet weight hash is exact, but live answer quality is
  unreliable under the official `i2_s` runtime. BitNet remains measurable; the
  browser now defaults interactive use to 8B Q4.

- Deployed `vinfer-0.8.0` to the public 832 GiB SNP guest. The browser verifies
  11 attestation/receipt checks and refuses to encrypt until the boot HPKE key
  is trusted.
- The TEE console uses HPKE plus an exported ChaCha20-Poly1305 session key for
  encrypted prompt history, streamed token chunks, full response, metrics, and
  usage. TypeScript/Python interoperability and ciphertext-only wire tests pass.
- Registered the current boot at devnet PDA
  `7asixqGuMEbu4Dm89XRKJBMPaYPtCPjWLBGJxL7AX6h`. A live sealed request posted
  receipt index 0; `vinfer verify` returned `RESULT: OK` with every stage PASS.
- The deployed Playwright test authenticated, waited for trusted attestation,
  confirmed its unique prompt was absent from the request wire body, decrypted
  the sealed stream, and observed a confirmed receipt in 5.7 seconds.
- An isolated measured-boot/dm-verity guest passed immutable root/model checks
  and full attestation verification for BitNet. Public all-model cutover remains
  open because that image is only 64 GiB and intentionally isolated.

- Deployed `vinfer-0.7.0` with a Secure/HttpOnly/SameSite browser test session;
  anonymous generation is `401`, authenticated chat returns a real SNP receipt,
  and logout invalidates the session. The access code is ignored and mode 0600.
- Generated `payskill/inference.yaml` from `models.yaml`; pay 0.22 schema,
  provider sync, and catalog no-probe validation pass.
- A real `pay --sandbox` cycle passed: standard `PAYMENT-REQUIRED` 402, x402
  payment, post-payment bearer injection, usage observation, and origin response.
- Launched an independent 832 GiB SNP guest, registry-verified all 11 GLM
  shards, and cut the public API over only after all five runtimes passed.
- Registered the final five-model SNP binding on devnet at PDA
  `GbJUCjVMnzFe85hkvuoeGsG5NZXWDH7G8kT1p9bfGDg5`.
- `/measurements/` exposed 1,198 raw request measurements at that stage. The
  current deployed union contains 1,244 unique requests plus all four sessions;
  rendered navigation and filtering pass in headless Chromium.
- Live OpenAI testing passed eight JSON and one SSE completion with exact usage;
  an empty/EOS completion returned 200 instead of the previous intermittent 500.
- No public paid gateway or provider listing was published. Mainnet wallet
  configuration, paid-hostname catalog probes, and the no-refund conflict
  remain open. The live authenticated origin now posts devnet receipts.

## Execution Evidence

| Command/check | Result |
|---|---|
| `make test` | PASS: 54 Python tests, including separate browser/bearer credentials, HPKE interoperability, sealed streaming privacy, request caps, and receipt retention bounds |
| `make check` | PASS: Python tests, registry hash verification, generated-measurement drift check, web lint/static build, Solana formatting, and `git diff --check` |
| Request/session schema validation | PASS: 2,772 request records + 8 session records across raw artifacts, 0 errors |
| `cargo test --manifest-path solana/programs/verified_inference/Cargo.toml` | PASS: 2/2 |
| `anchor test --provider.cluster localnet --validator legacy` | PASS: 15/15; strict hash-only receipt IDL and Ed25519 introspection covered |
| `npm run lint` + `npm run test:e2e` | PASS; two live Chromium tests cover sealed traffic and route privacy |
| normal and static `npm run build` | PASS; static console deployed and exact chunk checked |
| `npm audit --audit-level=moderate` | PASS: 0 vulnerabilities |
| real report render | PASS: 952 retained requests, 4 sessions, 174,012-byte HTML with complete linked run provenance |
| sparse synthetic report render | PASS after empty-chart fix; previously crashed at prompt 128 |
| `vinfer verify /tmp/vinfer-082-rotation-receipt.json` | PASS: full live 0.8.2 chain, exact receipt index 1, no skips |
| `vinfer verify /tmp/vinfer-proxy-022-rotation-receipt.json` | PASS: full live 0.2.2 Claude-proxy chain and exact receipt index 0, no skips |
| Gitleaks full-history scan | PASS after authorized rewrite: 0 findings; removed paths/private URL/fingerprints absent from reachable history |
| pay PAY.md validation | PASS with `pay catalog check --no-probe`; intentionally non-publishable placeholder URL |
| runtime-YAML -> `pay skills provider sync` -> validator | PASS: generated from `models.yaml`; 4 endpoints walked |
| official pay sandbox gateway | PASS: 402 + `PAYMENT-REQUIRED` -> x402 payment -> authenticated origin -> usage/receipt response |
| strict live pay registry gate | PASS: all five priced registry models match the live API; listing remains unpublished because mainnet, paid-hostname, and live catalog probes are intentionally deferred |
| SSH read-only host/guest audit | PASS: host 6.17, SEV/ES/SNP enabled; guest `/dev/sev-guest`; no heavy commands |
| TLS checks | PASS: HTTP redirects to HTTPS; only 80/443 public; API/CVM forwards on loopback; oversized bodies return 413 |

## Evidence Table

### Machine, Recon, and Trust Legs

| Item | Status | Evidence |
|---|---|---|
| SSH key path-only rule | PASS | `.gitignore:9`; `infra/ssh_config:1-18`; history scan found no key blob. The private key was never opened by this audit. |
| Bare-metal role and launch control | PASS | Live SSH: EPYC 9555P, 128 CPUs, `/dev/kvm` + `/dev/sev`; host lacks `/dev/sev-guest`; one QEMU guest. |
| SEV/ES/SNP distinction | PASS | Live host flags `sev sev_es sev_snp`; KVM parameters all `Y`; guest has `/dev/sev-guest`. `recon/findings.md:7-20` records the current state. |
| Recon raw evidence currentness | PARTIAL | `recon/raw/` is the initial pre-enable run and says `/dev/sev` absent. Current reality is a prose banner plus run artifacts, not a fresh raw recon bundle. |
| Host/guest decision row | PASS | `recon/findings.md:11-17` records Row 1 host-control and a booted SNP guest. |
| NUMA topology | PASS | Live + `recon/raw/12_numa.txt`: NPS1, one node, CPUs 0-127, about 1.15 TB RAM. |
| STREAM SEV off/on | PARTIAL | `runs/all-sessions.jsonl` has off 346.19 and ES 256.10 GB/s; SNP 376.91 is a different run/day. Bare-metal 357.1 is separate. No current matched off/SNP pair. |
| Memory-latency anchor | MISSING | No memory-latency benchmark artifact or report section. |
| Leg A baseline | PARTIAL | Real llama/BitNet measurements exist, but not the required full grid. |
| Leg B SNP inference | PARTIAL | Real VMPL0 report, KDS verification, five-model live inference, and a reduced four-model twin matrix exist. GLM SNP measurements and the full matrix do not; mutable userspace is not measured. |
| Leg C direct/proxied Claude | PARTIAL | `runs/legC-full.jsonl` has 64 direct + 64 proxied rows, one Claude model. Grid is only prompts 128/1024, caps 128/512, n=8. |
| Leg D ladder | MISSING | No D records. `solana/.../verify_inference_proof.rs:7-12,46-54` explicitly says no verification. |

### Models, API, Attestation, Pricing, and pay.sh

| Item | Status | Evidence |
|---|---|---|
| Five required registry models | PASS | `models.yaml:7-72` contains BitNet, 8B Q4/Q8, 70B Q4, and GLM-5.2 with paths, hashes, contexts, legs, and prices. |
| GLM-5.2 first-class measurement/report | PARTIAL after fix | `runs/glm-bench.jsonl` has 10 baseline rows at prompt 16; the report shows the baseline, registry price, and explicit missing SNP/MoE comparison. The model is now live in the 832 GiB SNP guest, but the required matched SNP experiment is still missing. |
| External upstream scope | PASS | Claude is the only external API upstream; GLM and the other registry models use local open weights. |
| `models.yaml` single source | PASS after fix | `infra/run-servers.sh` delegates to `server/launch.py`, which consumes registry weights, runtime, port, context, and template. No serving model table remains. |
| Runtime interface names | PASS after fix | `server/runtimes/base.py` defines `load/tokenize/stream_generate`; read-only health/tokenize/path probes passed against all five real host runtimes. |
| OpenAI-compatible endpoint | PASS after fix | Live `POST /v1/chat/completions`; eight JSON + one SSE requests passed. llama.cpp usage is required/validated and an empty completion returned 200. Free models/attestation/receipt GETs remain. |
| Authenticated browser test path | PASS after fix | Live anonymous POST is 401; session login, real completion, and logout/401 cycle passed. Cookie is Secure, HttpOnly, SameSite=Strict; static bundle contains no access code. |
| `/v1/infer` thin alias | PARTIAL | `server/main.py:619-640` is a separate raw-prompt generation path, not a call-through to chat completions. Endpoint-shape changes are Category B. |
| Pricing derivation | PARTIAL | `report/pricing.py` reads throughput and documented constants, then writes prices. Receipt amortization assumes 128 output tokens/request; this is not data-driven per request distribution. |
| Quote formula | WRONG | Active pay runtime authorizes a configured `$0.50` ceiling and settles observed tokens. It does not calculate prompt tokens plus requested maximum output before payment. |
| Upfront, no-refund settlement | WRONG | Official `x402-upto` refunds the unused authorized ceiling. This is documented, not presented as satisfying the older requirement. |
| x402 interoperability | PARTIAL after fix | Standard pay 0.22 `PAYMENT-REQUIRED` sandbox cycle passes for `stream:false`, and the live five-model registry check passes. The origin now posts receipts, but paid SSE metering, mainnet configuration, and a paid hostname remain deferred. |
| pay.sh generation pipeline | PASS after fix | `models.yaml` -> `generate_runtime.py` -> provider sync -> generated PAY/OpenAPI -> catalog check passes. Generator never publishes. |
| Listing response guarantee | PASS for the live origin | Completion carries the signed receipt, attestation grade, confirmed receipt PDA, and devnet transaction. pay.sh publication remains intentionally blocked on mainnet and a paid hostname. |
| Binding v2 formula | PASS | `server/main.py`; live KDS verification proved pubkey + complete registry hash + build hash binding. |
| Registry hash exact definition | PASS after fix | Live build 0.8.2 uses all five hash-bearing pairs (`49dc89...`); attestation lists all five runtimes in `active_models`. Devnet PDA exact-match passed. |
| PDA binding version / v1 compatibility | PASS | Account carries both version/hash; CLI prints v1/v2 and handles both (`cli/vinfer.py:185-201`). |
| Add-a-model flow | PARTIAL after fix | Bench now uses n=10; launcher, pricing, pay runtime, provider sync, and validation consume `models.yaml`. Automated restart/re-attest/PDA update and a tiny fixture remain missing. |

### Measurement Schema and Matrix

| Item | Status | Evidence |
|---|---|---|
| Frozen request schema fields/enums | PASS | `harness/schema.json:7-41` matches the required fields and enums. |
| Frozen session schema | PASS | `harness/session_schema.json:7-20` has all required session measurements. |
| No schema fork in Git history | PASS | Request schema was added once in `7f73259` and has no later committed fork. |
| Existing JSONL schema validity | PASS | Structured validation: 2,772 request + 8 session rows, zero errors. |
| Measurement semantic completeness | PARTIAL after fix | Registry-driven migration filled legacy empty `quant` values. The 1,244 curated browser rows remain historical measurements with zero receipt-post/CU fields; live posting now works but those old experiments have not been rerun. |
| Resumability | PARTIAL | `harness/runner.py:35-49,125-156` skips deterministic run IDs by scanning output; no required completed-cell manifest exists. |
| Warmup discard | PASS | `report/generate.py:75-107` drops first two per reconstructed cell while retaining raw rows. |
| Pinned threads / fixed NUMA | PARTIAL | NUMA labels and thread counts are recorded, but runtime launch uses `-t`; no complete CPU-affinity evidence exists for every run. |
| Legs A/B full Cartesian grid | WRONG | Missing GLM-SNP, prompt 8192, output 1024, guest 64/128 threads, most HPKE cells; current reduced cells mostly n=10. |
| Leg C required grid | WRONG | Prompts 8192 and output cap 1024 absent; n=8, not n>=10. |
| Leg D n=5/rung and SEV comparison | MISSING | No D rows. |

### Solana and Verification

| Item | Status | Evidence |
|---|---|---|
| `register_attestation` fields | PASS | `state.rs:23-51`; account contains key, measurement, report/registry hashes, runtime, grade, version, slot, counters. |
| Honest grade | PASS | Current live/report/PDA are SNP; legacy ES remains launch-only. |
| Receipt hashes only | PASS | `state.rs:54-73`; prompt/response/model hashes, key, timestamp/index/slot only. |
| Native ed25519 verification | PASS | `ed25519.rs:35-110` requires the immediately preceding native program instruction, one signature, self-contained offsets, exact key and message. |
| Merkle batch | PASS | Batch account/instruction and 14/14 localnet tests; 32 receipts measured at 11,895 program CU. |
| Groth16 alt_bn128 verification | MISSING | Stub records hashes and `verified=false`; no Groth16 dependency or syscall. |
| Mainnet economics projection | MISSING | No base/p50/p90 priority-fee, rent, single/batch, $/receipt, and $/1M complete projection. |
| `vinfer verify` full chain | PASS | Recorded SNP receipt passed KDS chain, policy, key binding, PDA, registry, signature, and exact receipt contents/index 0. |
| Live boot on-chain receipt continuity | PASS | Build 0.8.2 is registered at `3Ujr6...HtRCUk`; an 8B request posted receipt index 1 and full `vinfer verify` returned `RESULT: OK`. Proxy build 0.2.2 is registered at `EQpcM...LLZwPb`; its confirmed receipt index 0 also passed the full chain. |

### Encryption, Privacy, Secrets, and TLS

| Item | Status | Evidence |
|---|---|---|
| HPKE private-key lifecycle | PASS | `server/main.py:92-100`; `hpke_box.py` uses generated in-memory X25519 key; no persistence/log call. |
| Attestation before encryption | PASS | CLI/harness and `web/app/page.tsx` fail closed. Browser Run stays disabled until AMD chain, policy, signed HPKE key, and attestation PDA checks all pass. |
| Signed HPKE binding | PASS | `cli/attest_verify.py:94-114`; domain-separated signature by the SNP-bound Ed25519 key. |
| Input-only vs bidirectional truth | PASS | `/v1/infer_sealed` is input-only. `/v1/chat_e2e` seals chat history, streamed deltas, complete response, metrics, and usage. Baseline/Claude routes are explicitly TLS-only. |
| On-chain plaintext/user identifiers | PASS | Anchor state and receipt construction use hashes only. No prompt, response, or user ID field. |
| Application/model logging | PASS | Source and guest log scan found no prompt/message/content markers or key markers. Harness JSONL has schema-only metrics. |
| Edge access logging | PARTIAL | Caddy logs had remote IP/User-Agent but no bodies/authorization. `8b5d173` disabled new access logs and was deployed; old files remain because box deletion was forbidden. |
| Full-history secret hygiene | PASS after rewrite | Gitleaks 8.30.1 found 0 findings. Searches found zero private-URL, SSH-fingerprint, or removed-path commits. `.gitignore` predates secret files. |
| Ignored/generated worktree scan | PASS after fix | Full directory scan found one real credential only in ignored `.env.local` and six generic-key false positives only in ignored `.next/` build output. Neither is tracked; `.env.local` was changed from mode 0644 to 0600 without exposing its value. |
| Anthropic secret source | PASS | Proxy reads `ANTHROPIC_API_KEY` from the ignored environment file; no tracked value. |
| Leg C privacy honesty | PASS | Proxy only targets Anthropic; report/UI state Anthropic sees plaintext and inference is not verified. |
| Tachyon code containment | PASS | No vendored source object in Git history. |
| Tachyon information containment | PASS after rewrite | No source was vendored. The authorized rewrite removed private-upstream notes and their URL from every reachable commit; only public, high-level product copy remains. |
| External TLS | PASS | Caddy automatic TLS/HSTS; HTTP returns 308; upstream API and guest forwarding bind loopback. |
| AWS use | PASS | None found. Caddy is a self-hosted web/TLS reverse proxy on Sunburst, not an AWS service. |

### Deliverables

| Item | Status | Evidence |
|---|---|---|
| CLI infer/attest/verify/bench/receipts | PASS | Commands exist; full verify executed. Direct testing uses origin bearer auth; `vinfer pay` delegates payment to the official pay CLI. |
| Web streaming chat and metrics | PASS | Production/static builds pass; model/leg picker, streamed text, TTFT/tok/s/cost/grade/receipt panels exist. The deployed explanation distinguishes Caddy/TLS routing, loopback isolation, HPKE content privacy, operator SSH, and hash-only Solana data. |
| Web measurement visibility | PASS after fix | Both route forms return 200; deployed JSON and UI expose 1,244 unique request rows, warmup status, every frozen field via row details, and all four sessions. |
| Web verified pass/fail + tx link | PASS after fix | Browser independently verifies AMD chain/report, local policy, HPKE binding, registry PDA, receipt signature/content, and exact receipt PDA. Live Playwright observed `verified`, a trusted prompt key, `end-to-end sealed`, and a confirmed receipt link. |
| Web zkML scope honesty | PASS after fix | Public chunk says verifier is a stub, no measurements, integrity not input privacy. |
| Report required analyses | PARTIAL after fix | GLM baseline and the missing matched SNP comparison are explicit. Full mainnet economics, measured zkML ladder, Groth16-vs-hash, and sourced GPU projections remain absent. |
| Report provenance links | PASS after fix | Every section footer contains the complete contributing run/session IDs linked to exact browser filters (`report/generate.py`). |
| Report attestation costs | PARTIAL after fix | Positive phase samples report median/p99/n; zero sentinels are `not recorded`, not zero cost. Per-response post/confirm/CU/fees remain unmeasured. |
| LEDGER deliverable | MISSING by owner direction | The owner later requested redundant Markdown removal. Current state/evidence now live in `README.md`/`AUDIT.md`, and unresolved work lives in `FIXES.md`; this intentionally removes the original checklist's separate `LEDGER.md` deliverable. |
| Mock-server harness pipeline | MISSING | Previous agent deleted the mock; Pass 2 could not run the required pipeline. Unit isolation tests and live server checks passed, but that is not the requested mock pipeline. |
| Tiny add-model validation | MISSING | No tiny runtime/fixture or automated end-to-end flow; running against the live service would only fail unknown-model validation and perturb artifacts. |

## Residual Risk

- The SNP report proves a launch measurement and binds an ephemeral key to
  guest-declared digests. It does not currently measure the mutable root,
  Python source, runtime binaries, or every model shard.
- Receipt hashes do not reveal plaintext directly, but low-entropy content can
  still be tested by guessing and hashing candidate values.
- Current report economics combine historical ES cells and reduced SNP cells;
  they are not the complete authoritative experiment.
