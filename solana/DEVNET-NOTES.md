# Devnet deployment — verified_inference

Live on Solana **devnet** (2026-07-16). The receipt-verification pipeline now
has real on-chain records; `vinfer verify`'s "registry PDA" and "on-chain
receipt" steps can point here instead of SKIPPED.

## Addresses

- **Program ID:** `Dp5LxL9XHZUVXK129rxwBafqHMg1Y29Zda2svx8vXEkx`
  https://explorer.solana.com/address/Dp5LxL9XHZUVXK129rxwBafqHMg1Y29Zda2svx8vXEkx?cluster=devnet
- Upgrade authority / deployer: `595GKA6hUnUKaZLJq252MzHy2kABwWLBThBCq3nYdruo`
  (keypair `solana/.devnet-deployer.json`, gitignored — never committed)
- ProgramData: `G76Y7Ut8cw8bPjnoDQDxobRiGi3ymEAfKC4TRDT2tFbL`, slot 476747930

## Live demo transactions (scripts/devnet-demo.ts)

Binding v2 end to end with a fresh enclave ed25519 key:

- **register_attestation** (binding_version=2)
  - registry_hash `1dc886bab12589ca8a7a96766efb2e5e77082e04dd9954974faf0adf9be4c835`
  - attestation PDA `J8k2rwiw1yLaBX9xQ7cSFWhFrdKoK8nEgtzoTxYBDJRH`
  - tx `4V9m3Hfha8dGX2N43gc9X8Vvb1ccNz7jC1SCZHYxS1KpxnqZEqF3tvrJgc6KPQNLjLy1o9xMUsZMnASzCh5Dp6n7`
  - **CU 10,171**
- **post_receipt** (native ed25519 ix + program ix, sysvar introspection)
  - receipt PDA `BTVqR2PkEPU2moWwYceYGM1xkxuV856c1bq1heY6w61q` (index 0)
  - tx `uvgeoTeLh1tvmAaczMRk1UhbK6sY3iVsmoExNwTBEqNbYwxbnYHQ53eSFkkwgJ8NVf14hpjdBXbcxwRtqcmF69s`
  - **CU 13,580** (ed25519 precompile + program)

## Honest re-registration (audit B2/B3, 2026-07-16)

The original demo above registered `attestation_grade = Mock`, which the audit
flagged: after the "remove all mock" order, no live record should claim a mock
grade, and `vinfer verify` could not go green against a zero-sig scratch receipt.
Fixed:

- Enum `AttestationGrade::Mock` → **`NoTee`** (state.rs) — the honest grade for a
  key generated with plaintext memory (no TEE). Discriminant is unchanged (2), so
  the on-chain byte and PDA layout are identical; only the source-level name and
  the client decode (`cli/devnet.py` 2 → `"none"`) change. The deployed bytecode
  never stored the *name* "Mock" — only the discriminant — so the on-chain record
  carries no mock semantics.
- `scripts/devnet-demo.ts` now uses a **persistent** enclave key
  (`solana/.demo-enclave.json`, gitignored) and registers grade `noTee`, and
  ships a **self-verifiable receipt** (`runs/demo-receipt.json`) embedding the
  attestation doc so `vinfer verify` is green offline + cross-anchored on devnet.

Live honest demo (grade `none`/NoTee, binding v2):

- enclave pubkey `b07e57ca5fdb1ed1750fe7c78e49c1b5700fa21922034b293af34e97da86c1ec`
- attestation PDA `9qKYSKdbqXSmTprenTTfZkknuuq4Rt9Ug3HvcZXWsHdG`
  - register tx `4RNbDQNWPaRYppFE3BrYD7ntrG6QdutPgd1QafQMNMBNQtMDqT3WVzMrVLYEbRNG9Sqq4S52UXXSAHNWLuonxfTY` (CU 8,671)
- receipt[0] PDA `9huWQGCysVz7oSVZQa83Gm5QbdokXgiL7RRZSNZXjQRh`
  - post tx `5S4DsHp52bVJtmie3qd1bDz2iQemaFyoehpefv3iChh92moT2qop7Q7FoKL7aMcu1nkorKbCsKyQ8TCxALJ3UhAa` (CU 13,580)

`vinfer verify runs/demo-receipt.json` → all PASS, SNP row SKIPPED (grade `none`
has no hardware report — the honest outcome; a real CVM receipt carries grade
`snp`/`launch-only` and the KDS chain runs for real).

**RESOLVED:** after a deployer top-up, the program was upgraded in place with the
`NoTee` build (deploy slot 476778319, sig `4oYTBd4tGXcVtGPcSWb4SpCdZJxAgE6SntXAMH2kJ2Hhb99FkbwXNLZ3YBNiDKLiD3wtgDsEwmur24Gjdh64Kb5y`).
`vinfer verify runs/demo-receipt.json` re-confirmed fully green post-upgrade.
Gotcha repeated itself: plain `anchor deploy` died on throttled devnet RPC
("Data writes to account failed: Max retries exceeded", stranded 1.59 SOL
buffer) — reclaim with `solana program close --buffers`, then
`solana program deploy --with-compute-unit-price 50 --max-sign-attempts 200`.

## Devnet CU vs localnet (CU-NOTES.md)

register_attestation 10,171 (devnet) vs 8,671 (localnet) — devnet higher due to
priority compute-unit price + loader overhead; both within expected range.
post_receipt 13,580 vs ~12,080. Use devnet numbers for the mainnet fee
projection in the report.

## Deploy cost / ops

- Deployer funded ~3 SOL via airdrop (devnet, free). Program account rent
  (~1.6 SOL for 224KB .so) + tx fees; ~1.4 SOL remained after first attempt.
- **Gotcha:** the first `anchor deploy` stalled on throttled devnet RPC leaving
  a buffer with a TRUNCATED ELF (`invalid section header`). Fix: `solana
  program close <buffer>` to reclaim the ~1.6 SOL, then `solana program deploy`
  fresh with `--with-compute-unit-price 50 --max-sign-attempts 200`. Don't
  reuse a buffer from a stalled deploy without verifying its ELF.

## Next (P4/P5)

- Point `vinfer verify` at devnet: fetch the attestation PDA, check
  registry_hash matches the served registry, confirm the receipt PDA exists.
- Merkle-batched receipts on devnet for the per-receipt vs batched cost chart.
- verify_inference_proof: wire groth16-solana when leg D resumes (post-B200s).
