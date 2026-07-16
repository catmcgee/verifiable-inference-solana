use anchor_lang::prelude::*;

use crate::constants::*;
use crate::ed25519::require_ed25519_verification;
use crate::state::{AttestationAccount, ReceiptAccount};

#[derive(Accounts)]
#[instruction(enclave_ed25519_pubkey: [u8; 32])]
pub struct PostReceipt<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,

    /// The enclave must have a registered attestation; an unregistered enclave
    /// fails here with AccountNotInitialized. Mutable: receipt_count advances.
    #[account(
        mut,
        seeds = [ATTESTATION_SEED, enclave_ed25519_pubkey.as_ref()],
        bump = attestation.bump
    )]
    pub attestation: Account<'info, AttestationAccount>,

    #[account(
        init,
        payer = payer,
        space = 8 + ReceiptAccount::INIT_SPACE,
        seeds = [
            RECEIPT_SEED,
            enclave_ed25519_pubkey.as_ref(),
            attestation.receipt_count.to_le_bytes().as_ref()
        ],
        bump
    )]
    pub receipt: Account<'info, ReceiptAccount>,

    /// CHECK: instructions sysvar, address-checked; introspected for the
    /// preceding ed25519-program instruction.
    #[account(address = solana_instructions_sysvar::ID)]
    pub instructions_sysvar: UncheckedAccount<'info>,

    pub system_program: Program<'info, System>,
}

/// Canonical signed message: prompt_hash || response_hash || model_hash || timestamp_le
pub fn receipt_message(
    prompt_hash: &[u8; 32],
    response_hash: &[u8; 32],
    model_hash: &[u8; 32],
    timestamp: i64,
) -> [u8; RECEIPT_MSG_LEN] {
    let mut msg = [0u8; RECEIPT_MSG_LEN];
    msg[0..32].copy_from_slice(prompt_hash);
    msg[32..64].copy_from_slice(response_hash);
    msg[64..96].copy_from_slice(model_hash);
    msg[96..104].copy_from_slice(&timestamp.to_le_bytes());
    msg
}

#[allow(clippy::too_many_arguments)]
pub fn handle_post_receipt(
    ctx: Context<PostReceipt>,
    enclave_ed25519_pubkey: [u8; 32],
    prompt_hash: [u8; 32],
    response_hash: [u8; 32],
    model_hash: [u8; 32],
    timestamp: i64,
) -> Result<()> {
    let message = receipt_message(&prompt_hash, &response_hash, &model_hash, timestamp);
    require_ed25519_verification(
        &ctx.accounts.instructions_sysvar,
        &enclave_ed25519_pubkey,
        &message,
    )?;

    let attestation = &mut ctx.accounts.attestation;
    let receipt = &mut ctx.accounts.receipt;
    receipt.enclave_ed25519_pubkey = enclave_ed25519_pubkey;
    receipt.prompt_hash = prompt_hash;
    receipt.response_hash = response_hash;
    receipt.model_hash = model_hash;
    receipt.timestamp = timestamp;
    receipt.index = attestation.receipt_count;
    receipt.slot = Clock::get()?.slot;
    receipt.bump = ctx.bumps.receipt;

    attestation.receipt_count = attestation
        .receipt_count
        .checked_add(1)
        .expect("receipt_count overflow");

    Ok(())
}
