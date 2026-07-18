# Project Ledger

This ledger records verified project state, decisions, and external spend. It
does not contain credentials, key fingerprints, prompt or response plaintext,
or private-upstream implementation notes.

## 2026-07-18

| Area | Result |
|---|---|
| Public console | `https://console.213.239.141.40.sslip.io` deployed and checked on desktop/mobile Chromium. |
| Public API | `https://verified-inference.213.239.141.40.sslip.io`; HTTPS enters through Caddy on Sunburst. Application traffic does not use SSH. |
| TEE inference | Five local open-weight models are live in an 832 GiB SEV-SNP guest. Public userspace remains mutable and is labeled `guest-declared`. |
| Browser privacy | TEE chat history and responses are sealed end to end after the browser verifies AMD KDS, policy, key binding, and the attestation PDA. The edge sees routing metadata and ciphertext. |
| Solana devnet | Current attestation PDA: `7asixqGuMEbu4Dm89XRKJBMPaYPtCPjWLBGJxL7AX6h`. A sealed request posted receipt index 0 and the full CLI verification chain returned `RESULT: OK`. |
| On-chain data | Attestation metadata and fixed-size prompt, response, and model hashes only. No prompt, response, message, or user identifier field exists in the receipt account. |
| Measured boot | An isolated BitNet dm-verity guest passed immutable root/model verification. It has not replaced the public all-model guest. |
| Payments | Official pay/x402 sandbox flow passed. No provider listing, paid gateway, or mainnet configuration was published. |
| Measurements | Browser exposes 1,244 unique frozen-schema requests and four session records. The required full experiment matrix is incomplete. |
| Tests | 47 Python tests, 15 Anchor localnet tests, Rust formatting/Clippy, frontend lint/build, Playwright privacy flow, dependency audit, unused-code scan, and duplicate scan passed. |
| History | Authorized rewrite removed obsolete ledgers/plans/private notes from all reachable commits. Gitleaks found zero findings. |
| External spend | No AWS use. No mainnet spend. Solana activity used devnet. No pay.sh listing was published. |

## Decisions

- Keep the public test console behind authenticated browser sessions; add x402
  as a separate payment gateway rather than embedding payment in the console.
- Keep plaintext outside the TEE route explicitly out of scope: the baseline is
  TLS-only, and Anthropic sees Claude-proxy prompts.
- Defer ZK proof work and mainnet deployment. Do not claim either as complete.
- Do not claim public userspace or model execution is measured until the tested
  immutable-image approach is applied to the public all-model guest.

## Outstanding Work

- Cut the public all-model guest over to an immutable measured root and model
  manifest, then re-attest and update the devnet registry.
- Run the missing matched GLM SNP, full A/B, Claude, memory-latency, and matched
  STREAM experiments before drawing complete break-even conclusions.
- Resolve pay/x402 no-refund semantics and configure mainnet only when the
  operator intentionally chooses to publish the paid service.
