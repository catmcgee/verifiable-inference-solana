# Independent Audit: verified-inference

Audit date: 2026-07-17. The user's audit brief is the authoritative specification.
Repository plans, READMEs, prior audit claims, and prior-agent conversation notes
were treated only as evidence.

## Executive Summary

This is a real SNP/devnet prototype, not a specification-complete verified
inference service.

Bluntest findings first:

1. **The browser does not verify attestation.** It fetches and renders a
   server-provided grade and hashes. The public UI now says "not performed in
   browser", but the required pass/fail verifier is missing. Receipt links also
   fall back to the registry program, not the receipt transaction.
2. **The flagship/report thesis is missing.** GLM-5.2 has ten baseline samples
   at one small shape, is unavailable in the live SNP guest, is absent from the
   report model order, and has no SNP, MoE-vs-dense, or Z.ai-price comparison.
3. **The paid surface is not conformant x402/pay.sh.** The live challenge calls
   itself `experimental` / `vinfer-session-v1`; it refunds unused authorization,
   while the specification requires settled-upfront, no-refund charging. Paid
   responses carry a signed receipt, but on-chain posting is a separate step.
4. **The required experiment matrix was not run.** Current useful data covers
   four local models, prompts 128/1024, output 128, guest threads 16/32, and a
   narrow HPKE slice. Prompt 8192, output 1024, guest threads 64/128, full HPKE,
   GLM-in-SNP, memory latency, and all leg-D rungs are absent.
5. **Leg D is not implemented.** `verify_inference_proof` stores a commitment
   and always sets `verified=false`; it performs no Groth16/alt_bn128 verification.
6. **Private Tachyon internals were committed to public history.** HEAD is
   redacted, and no source code was vendored, but the old blobs remain in Git
   history. Rewriting history is intentionally left to the owner.
7. **The strong part is real.** `vinfer verify runs/snp-receipt.json` passed the
   SNP report, AMD VCEK->ASK->ARK chain, v2 binding, registry PDA, receipt
   signature, and exact on-chain receipt record with no skips.
8. **Encryption is real but scoped.** CLI/harness clients verify SNP and the
   signed HPKE key before encrypting. `/v1/infer_sealed` protects input only;
   `/v1/chat_e2e` seals both directions. The mutable guest root still prevents
   the attestation from independently proving the Python code or weights run.
9. **TLS is live and AWS is not used.** Caddy is the TLS reverse proxy on the
   Sunburst host; HTTP redirects to HTTPS and upstream listeners are loopback.
   No AWS SDK, service, credential, deployment, or account use was found.
10. **No secret was found.** Gitleaks over full Git history returned zero
    findings, corroborated by a path-only manual history scan.

## Execution Evidence

| Command/check | Result |
|---|---|
| `make test` | PASS: 12 Python tests; standalone x402 session suite PASS |
| Request/session schema validation | PASS: 2,772 request records + 8 session records across raw artifacts, 0 errors |
| `cargo test --manifest-path solana/programs/verified_inference/Cargo.toml` | PASS: 2/2 |
| `anchor test --provider.cluster localnet --validator legacy` | PASS after fixture fix: 14/14; receipt 12,080 CU; batch 11,895 CU; proof stub 8,961 CU |
| `npm run lint` | PASS after noninteractive lint fix |
| normal and static `npm run build` | PASS; static console deployed and exact chunk checked |
| `npm audit --audit-level=moderate` | PASS: 0 vulnerabilities |
| real report render | PASS: 952 retained requests, 4 sessions, 41,350-byte HTML |
| sparse synthetic report render | PASS after empty-chart fix; previously crashed at prompt 128 |
| `vinfer verify runs/snp-receipt.json` | PASS: full chain, exact receipt index 0, no skips |
| Gitleaks full-history scan | PASS: 0 findings |
| pay PAY.md validation | Frontmatter PASS; live probe indeterminate for paid POST |
| runtime-YAML -> `pay skills provider sync` -> validator | FAIL: generated provider lacks endpoint `description`; source YAML is stale |
| SSH read-only host/guest audit | PASS: host 6.17, SEV/ES/SNP enabled; guest `/dev/sev-guest`; no heavy commands |
| TLS checks | PASS: HTTP 308 to HTTPS; only 80/443 public; API/CVM forwards on loopback |

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
| Leg B SNP inference | PARTIAL | Real VMPL0 report, KDS verification, four-model inference, and reduced twin matrix exist. GLM and the full matrix do not; mutable userspace is not measured. |
| Leg C direct/proxied Claude | PARTIAL | `runs/legC-full.jsonl` has 64 direct + 64 proxied rows, one Claude model. Grid is only prompts 128/1024, caps 128/512, n=8. |
| Leg D ladder | MISSING | No D records. `solana/.../verify_inference_proof.rs:7-12,46-54` explicitly says no verification. |

### Models, API, Attestation, Pricing, and pay.sh

| Item | Status | Evidence |
|---|---|---|
| Five required registry models | PASS | `models.yaml:7-72` contains BitNet, 8B Q4/Q8, 70B Q4, and GLM-5.2 with paths, hashes, contexts, legs, and prices. |
| GLM-5.2 first-class measurement/report | WRONG | Only `runs/glm-bench.jsonl` (10 baseline rows, prompt 16). Live status is `runtime-unavailable`; `report/generate.py:23` omits GLM. No required comparisons. |
| Z.ai API prohibition | PASS | Search found reference text only; no Z.ai endpoint/client call. GLM weights came from open weights. |
| `models.yaml` single source | WRONG | `infra/run-servers.sh:24-29` duplicates every model path, runtime, port, and GLM flag. |
| Runtime interface names | WRONG | `server/runtimes/base.py:9-26` defines `generate/chat/chat_stream`, not required `load/tokenize/stream_generate`. |
| OpenAI-compatible endpoint | PASS | Live `POST /v1/chat/completions`; free models/attestation/receipt GETs. |
| `/v1/infer` thin alias | PARTIAL | `server/main.py:386-404` is a separate raw-prompt generation/payment path, not a call-through to chat completions. Endpoint-shape changes are Category B. |
| Pricing derivation | PARTIAL | `report/pricing.py` reads throughput and documented constants, then writes prices. Receipt amortization assumes 128 output tokens/request; this is not data-driven per request distribution. |
| Quote formula | PASS | `server/x402/middleware.py:45-53`; live bitnet challenge quoted 124 micro-USDC for the test prompt + max output. |
| Upfront, no-refund settlement | WRONG | `middleware.py:200-220` and `session.py:190-200` explicitly refund the unused quote. |
| x402 interoperability | WRONG | Live challenge: `paymentProtocol=experimental`, `scheme=vinfer-session-v1`, devnet. `server/x402/DESIGN.md` states it is non-interoperable. |
| pay.sh generation pipeline | WRONG | Generator emits PAY.md/OpenAPI only. Stale `payskill/generated/pay-server.yaml` points to `cat-verif.example`; sync output fails validator for missing endpoint descriptions. |
| Listing response guarantee | WRONG | Live 402 note says on-chain posting is separate. The response does not include attestation grade, and the listing cannot promise an on-chain receipt ID per paid response. |
| Binding v2 formula | PASS | `server/main.py:130-135`; full receipt verification proved pubkey + active registry hash + build hash binding. |
| Registry hash exact definition | PARTIAL | `make verify-registry` hashes all five models (`49dc89...`); live attestation hashes only four healthy runtimes (`e8c61b...`). Honest operationally, but not the specified single registry hash. |
| PDA binding version / v1 compatibility | PASS | Account carries both version/hash; CLI prints v1/v2 and handles both (`cli/vinfer.py:185-201`). |
| Add-a-model flow | WRONG | Bench uses n=8 (`harness/pricing_bench.py:23-30`), launch script needs manual edits, no reload/re-attest/PDA automation, and payskill target does not sync/validate. No tiny backend exists, so end-to-end validation could not run honestly. |

### Measurement Schema and Matrix

| Item | Status | Evidence |
|---|---|---|
| Frozen request schema fields/enums | PASS | `harness/schema.json:7-41` matches the required fields and enums. |
| Frozen session schema | PASS | `harness/session_schema.json:7-20` has all required session measurements. |
| No schema fork in Git history | PASS | Request schema was added once in `7f73259` and has no later committed fork. |
| Existing JSONL schema validity | PASS | Structured validation: 2,772 request + 8 session rows, zero errors. |
| Measurement semantic completeness | PARTIAL | 1,000/1,198 curated requests have empty `quant`; all 1,198 have zero receipt-post/CU fields because inference and chain posting were not integrated. |
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
| Live boot on-chain receipt continuity | PARTIAL | Current public boot advertises the attestation but has no per-response on-chain receipt integration; recorded proof comes from a previous registered boot. |

### Encryption, Privacy, Secrets, and TLS

| Item | Status | Evidence |
|---|---|---|
| HPKE private-key lifecycle | PASS | `server/main.py:92-100`; `hpke_box.py` uses generated in-memory X25519 key; no persistence/log call. |
| Attestation before encryption | PASS | `cli/vinfer.py:53-65,85-96` and `harness/runner.py:56-75` verify, fail closed, then seal. |
| Signed HPKE binding | PASS | `cli/attest_verify.py:94-114`; domain-separated signature by the SNP-bound Ed25519 key. |
| Input-only vs bidirectional truth | PASS after fix | `/v1/infer_sealed` returns plaintext inside TLS; `/v1/chat_e2e` seals output/metrics. Report now says exactly that (`999bd30`). |
| On-chain plaintext/user identifiers | PASS | Anchor state and receipt construction use hashes only. No prompt, response, or user ID field. |
| Application/model logging | PASS | Source and guest log scan found no prompt/message/content markers or key markers. Harness JSONL has schema-only metrics. |
| Edge access logging | PARTIAL | Caddy logs had remote IP/User-Agent but no bodies/authorization. `eb77370` disabled new access logs and was deployed; old files remain because box deletion was forbidden. |
| Full-history secret hygiene | PASS | Gitleaks 8.30.1: exit 0, 0 findings. Manual history grep found only variable/path references. `.gitignore` predates secret files. |
| Anthropic secret source | PASS | Proxy reads `ANTHROPIC_API_KEY` from env; no tracked value. |
| Leg C privacy honesty | PASS | Proxy only targets Anthropic; report/UI state Anthropic sees plaintext and inference is not verified. |
| Tachyon code containment | PASS | No vendored source object in Git history. |
| Tachyon information containment | PARTIAL | HEAD was redacted in `62f2031`; prior detailed notes remain in Git history and require owner-approved rewrite. |
| External TLS | PASS | Caddy automatic TLS/HSTS; HTTP returns 308; upstream API and guest forwarding bind loopback. |
| AWS use | PASS | None found. Caddy is a self-hosted web/TLS reverse proxy on Sunburst, not an AWS service. |

### Deliverables

| Item | Status | Evidence |
|---|---|---|
| CLI infer/attest/verify/bench/receipts | PASS | Commands exist; full verify executed. Paid inference requires the experimental credential flow. |
| Web streaming chat and metrics | PASS | Production/static builds pass; model/leg picker, streamed text, TTFT/tok/s/cost/grade/receipt panels exist. |
| Web verified pass/fail + tx link | MISSING | Browser performs no KDS/PDA verification; receipt fallback links to registry program, not receipt tx. UI now labels the gap (`ba2447f`). |
| Web zkML scope honesty | PASS after fix | Public chunk says verifier is a stub, no measurements, integrity not input privacy. |
| Report required analyses | WRONG | Missing GLM/Z.ai, MoE-vs-dense, full mainnet economics, measured zkML ladder, Groth16-vs-hash, and numeric GPU projection based only on sourced assumptions. |
| Report provenance links | WRONG | Footers provide count + min/max run ID, not links or the complete run IDs behind each chart (`report/generate.py:110-118`). |
| Report attestation costs | PARTIAL | Aggregates many zero fields as observations; this can hide the measured HPKE refresh cost and chain-post absence. |
| LEDGER substance | PARTIAL | Contains real command/results/decisions, but also stale contradictions and previous private-upstream detail in history. Not pure theater, not a reliable current-state source. |
| Mock-server harness pipeline | MISSING | Previous agent deleted the mock; Pass 2 could not run the required pipeline. Unit isolation tests and live server checks passed, but that is not the requested mock pipeline. |
| Tiny add-model validation | MISSING | No tiny runtime/fixture or automated end-to-end flow; running against the live service would only fail unknown-model validation and perturb artifacts. |

## Residual Risk

- The SNP report proves a launch measurement and binds an ephemeral key to
  guest-declared digests. It does not currently measure the mutable root,
  Python source, runtime binaries, or every model shard.
- Receipt hashes are commitments, not confidentiality against guessed prompts.
- Current report economics combine historical ES cells and reduced SNP cells;
  they are not the complete authoritative experiment.
- Historical Git blobs still contain private-upstream analysis and require an
  explicit history-rewrite decision before public publication.
