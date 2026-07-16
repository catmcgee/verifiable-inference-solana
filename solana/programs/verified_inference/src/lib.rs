//! verified_inference — attestation registry + inference receipts + zkML
//! proof records for the TEE cost/trust measurement harness (see /PLAN.md,
//! "Solana: attestation registry + receipts").

pub mod constants;
pub mod ed25519;
pub mod error;
pub mod instructions;
pub mod state;

use anchor_lang::prelude::*;

pub use constants::*;
pub use instructions::*;
pub use state::*;

declare_id!("Dp5LxL9XHZUVXK129rxwBafqHMg1Y29Zda2svx8vXEkx");

#[program]
pub mod verified_inference {
    use super::*;

    /// Register an enclave attestation. One per CVM boot; re-registering the
    /// same enclave pubkey fails (PDA init).
    pub fn register_attestation(
        ctx: Context<RegisterAttestation>,
        args: RegisterAttestationArgs,
    ) -> Result<()> {
        instructions::register_attestation::handle_register_attestation(ctx, args)
    }

    /// Record a single signed inference receipt. Requires a preceding
    /// ed25519-program instruction verifying the enclave's signature over
    /// prompt_hash || response_hash || model_hash || timestamp_le.
    pub fn post_receipt(
        ctx: Context<PostReceipt>,
        enclave_ed25519_pubkey: [u8; 32],
        prompt_hash: [u8; 32],
        response_hash: [u8; 32],
        model_hash: [u8; 32],
        timestamp: i64,
    ) -> Result<()> {
        instructions::post_receipt::handle_post_receipt(
            ctx,
            enclave_ed25519_pubkey,
            prompt_hash,
            response_hash,
            model_hash,
            timestamp,
        )
    }

    /// Record a merkle root over N receipt messages with a single ed25519
    /// signature check over merkle_root || num_receipts_le || timestamp_le.
    pub fn post_receipt_batch(
        ctx: Context<PostReceiptBatch>,
        enclave_ed25519_pubkey: [u8; 32],
        merkle_root: [u8; 32],
        num_receipts: u32,
        timestamp: i64,
    ) -> Result<()> {
        instructions::post_receipt_batch::handle_post_receipt_batch(
            ctx,
            enclave_ed25519_pubkey,
            merkle_root,
            num_receipts,
            timestamp,
        )
    }

    /// TODO(groth16): STUB — records the proof commitment only. Wire Light
    /// Protocol's groth16-solana alt_bn128 verification in P3/P4.
    pub fn verify_inference_proof(
        ctx: Context<VerifyInferenceProof>,
        proof_hash: [u8; 32],
        public_inputs_hash: [u8; 32],
        rung_id: u8,
    ) -> Result<()> {
        instructions::verify_inference_proof::handle_verify_inference_proof(ctx, proof_hash, public_inputs_hash, rung_id)
    }
}
