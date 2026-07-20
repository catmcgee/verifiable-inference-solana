# Compute-unit notes — verified_inference

The supported on-chain program has two operations: register an attestation and
post a signed receipt. Devnet measurements are the source of truth:

| instruction | CU consumed | network | measured |
|---|---:|---|---|
| register_attestation | 10,171 | devnet | 2026-07-16 |
| post_receipt | 13,580 | devnet | 2026-07-16 |

`post_receipt` is preceded by an ed25519 precompile instruction. Its signature
fee is charged by the runtime and is not included in the program CU above.

The attestation account retains one reserved `u64` from the original deployed
layout. It is not an API, seed, counter, or supported batching mechanism.

## Toolchain

- Anchor CLI and crate: 1.0.2
- Solana CLI: 4.0.0-rc.0
- Rust: 1.89.0, pinned by `rust-toolchain.toml`
- Anchor 1.x uses the modular `solana-instructions-sysvar` and
  `solana-sdk-ids` crates for instruction introspection and the ed25519 ID.
