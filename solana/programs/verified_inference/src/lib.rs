//! verified_inference — attestation registry and inference receipts.

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
}
