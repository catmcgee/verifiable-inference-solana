# Remaining Work

This file is the active backlog. Completed remediation and verification evidence
live in Git history and [AUDIT.md](AUDIT.md).

## Production trust boundary

1. Apply the tested measured-boot and dm-verity design to the public all-model
   guest so the attested key can only be used with approved code and weights.
2. Re-attest the immutable guest, update its devnet registry record, and rerun
   the full `vinfer verify` chain before changing `guest-declared` labels.
3. Preserve binding-v1 interpretation if the attestation account changes; do
   not reinterpret old records as binding v2.

## Measurement gaps

1. Run memory latency and a matched SEV-off/SNP STREAM pair.
2. Complete the local-model matrix: GLM, prompts through 8192, outputs through
   1024, 16/32/64/128 threads, concurrency 1/4/8, and every TEE HPKE cell with
   at least 10 retained runs per cell after two warmups.
3. Run the matched GLM SNP and MoE-versus-dense comparison.
4. Complete the Claude direct/proxied grid with at least 10 retained runs per
   cell.
5. Append real measurements under the frozen schema. Never invent receipt,
   compute-unit, latency, or cost values for historical runs.

## Payment publication

1. Decide whether pay's `x402-upto` refund behavior supersedes the earlier
   prompt-plus-maximum-output, no-refund requirement.
2. Add a stable paid hostname, intentional mainnet wallet configuration, and
   strict live catalog probes only when the service is ready to publish.
3. Keep the provider listing unpublished until every paid response exposes its
   confirmed on-chain receipt and all listed models pass live probes.

The generated runtime, provider sync, catalog validation, authenticated origin,
and sandbox payment cycle already pass.

## Maintenance

1. Add a tiny real model fixture that automates the one-entry add-model flow,
   including restart, re-attestation, and a temporary registry update.
2. Set and enforce a retention/deletion policy for old Caddy metadata logs.

## Intentionally deferred

- ZK/Groth16 proving remains out of scope until suitable GPUs are available.
- Mainnet deployment remains out of scope until the operator chooses to publish
  the paid service.
