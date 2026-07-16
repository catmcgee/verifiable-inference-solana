use anchor_lang::prelude::*;
use anchor_lang::solana_program::sysvar::instructions as instructions_sysvar_module;

use crate::constants::*;
use crate::ed25519::require_ed25519_verification;
use crate::error::VerifiedInferenceError;
use crate::state::{AttestationAccount, ReceiptBatchAccount};

#[derive(Accounts)]
#[instruction(enclave_ed25519_pubkey: [u8; 32])]
pub struct PostReceiptBatch<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,

    #[account(
        mut,
        seeds = [ATTESTATION_SEED, enclave_ed25519_pubkey.as_ref()],
        bump = attestation.bump
    )]
    pub attestation: Account<'info, AttestationAccount>,

    #[account(
        init,
        payer = payer,
        space = 8 + ReceiptBatchAccount::INIT_SPACE,
        seeds = [
            RECEIPT_BATCH_SEED,
            enclave_ed25519_pubkey.as_ref(),
            attestation.batch_count.to_le_bytes().as_ref()
        ],
        bump
    )]
    pub batch: Account<'info, ReceiptBatchAccount>,

    /// CHECK: instructions sysvar, address-checked; introspected for the
    /// preceding ed25519-program instruction.
    #[account(address = instructions_sysvar_module::ID)]
    pub instructions_sysvar: AccountInfo<'info>,

    pub system_program: Program<'info, System>,
}

/// Canonical signed batch message: merkle_root || num_receipts_le || timestamp_le
pub fn batch_message(
    merkle_root: &[u8; 32],
    num_receipts: u32,
    timestamp: i64,
) -> [u8; BATCH_MSG_LEN] {
    let mut msg = [0u8; BATCH_MSG_LEN];
    msg[0..32].copy_from_slice(merkle_root);
    msg[32..36].copy_from_slice(&num_receipts.to_le_bytes());
    msg[36..44].copy_from_slice(&timestamp.to_le_bytes());
    msg
}

pub fn handler(
    ctx: Context<PostReceiptBatch>,
    enclave_ed25519_pubkey: [u8; 32],
    merkle_root: [u8; 32],
    num_receipts: u32,
    timestamp: i64,
) -> Result<()> {
    require!(num_receipts > 0, VerifiedInferenceError::EmptyBatch);

    let message = batch_message(&merkle_root, num_receipts, timestamp);
    require_ed25519_verification(
        &ctx.accounts.instructions_sysvar,
        &enclave_ed25519_pubkey,
        &message,
    )?;

    let attestation = &mut ctx.accounts.attestation;
    let batch = &mut ctx.accounts.batch;
    batch.enclave_ed25519_pubkey = enclave_ed25519_pubkey;
    batch.merkle_root = merkle_root;
    batch.num_receipts = num_receipts;
    batch.timestamp = timestamp;
    batch.index = attestation.batch_count;
    batch.slot = Clock::get()?.slot;
    batch.bump = ctx.bumps.batch;

    attestation.batch_count = attestation
        .batch_count
        .checked_add(1)
        .expect("batch_count overflow");

    Ok(())
}
