use anchor_lang::prelude::*;

use crate::constants::*;
use crate::error::VerifiedInferenceError;
use crate::state::{AttestationAccount, AttestationGrade};

#[derive(Accounts)]
#[instruction(args: RegisterAttestationArgs)]
pub struct RegisterAttestation<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,

    /// One per CVM boot: `init` makes re-registering the same enclave pubkey
    /// fail at the runtime level ("account already in use").
    #[account(
        init,
        payer = payer,
        space = 8 + AttestationAccount::INIT_SPACE,
        seeds = [ATTESTATION_SEED, args.enclave_ed25519_pubkey.as_ref()],
        bump
    )]
    pub attestation: Account<'info, AttestationAccount>,

    pub system_program: Program<'info, System>,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone)]
pub struct RegisterAttestationArgs {
    pub enclave_ed25519_pubkey: [u8; 32],
    pub snp_measurement: [u8; 48],
    pub report_data_hash: [u8; 32],
    pub model_weights_hash: [u8; 32],
    pub runtime_version: String,
    pub attestation_grade: AttestationGrade,
}

pub fn handle_register_attestation(ctx: Context<RegisterAttestation>, args: RegisterAttestationArgs) -> Result<()> {
    require!(
        args.runtime_version.len() <= MAX_RUNTIME_VERSION_LEN as usize,
        VerifiedInferenceError::RuntimeVersionTooLong
    );

    let attestation = &mut ctx.accounts.attestation;
    attestation.enclave_ed25519_pubkey = args.enclave_ed25519_pubkey;
    attestation.snp_measurement = args.snp_measurement;
    attestation.report_data_hash = args.report_data_hash;
    attestation.model_weights_hash = args.model_weights_hash;
    attestation.runtime_version = args.runtime_version;
    attestation.attestation_grade = args.attestation_grade;
    attestation.slot = Clock::get()?.slot;
    attestation.receipt_count = 0;
    attestation.batch_count = 0;
    attestation.bump = ctx.bumps.attestation;

    Ok(())
}
