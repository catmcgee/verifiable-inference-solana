use anchor_lang::prelude::*;

use crate::constants::*;
use crate::error::VerifiedInferenceError;
use crate::state::ProofRecordAccount;

/// TODO(groth16): STUB. This records the proof commitment but performs NO
/// cryptographic verification. In P3/P4, wire Light Protocol's groth16-solana
/// (alt_bn128 syscalls) here: accept the raw proof (a, b, c) + public inputs,
/// run Groth16Verifier::verify(), and only then set `verified = true`.
/// The groth16-solana dependency is intentionally NOT pulled yet to keep the
/// P0 build clean.
#[derive(Accounts)]
#[instruction(proof_hash: [u8; 32])]
pub struct VerifyInferenceProof<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,

    #[account(
        init,
        payer = payer,
        space = 8 + ProofRecordAccount::INIT_SPACE,
        seeds = [PROOF_SEED, proof_hash.as_ref()],
        bump
    )]
    pub proof_record: Account<'info, ProofRecordAccount>,

    pub system_program: Program<'info, System>,
}

pub fn handle_verify_inference_proof(
    ctx: Context<VerifyInferenceProof>,
    proof_hash: [u8; 32],
    public_inputs_hash: [u8; 32],
    rung_id: u8,
) -> Result<()> {
    require!(
        (1..=4).contains(&rung_id),
        VerifiedInferenceError::InvalidRungId
    );

    let record = &mut ctx.accounts.proof_record;
    record.proof_hash = proof_hash;
    record.public_inputs_hash = public_inputs_hash;
    record.rung_id = rung_id;
    // TODO(groth16): flip to true only after real on-chain Groth16
    // verification succeeds. Never true in the stub.
    record.verified = false;
    record.slot = Clock::get()?.slot;
    record.bump = ctx.bumps.proof_record;

    msg!(
        "proof record stored (STUB — no cryptographic verification performed), rung {}",
        rung_id
    );

    Ok(())
}
