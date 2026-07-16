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
