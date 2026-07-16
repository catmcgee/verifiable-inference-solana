//! Ed25519 signature verification via instruction introspection.
//!
//! We NEVER verify ed25519 in-program (no syscall exists and a BPF
//! implementation would be absurdly expensive / unsafe). Instead the client
//! places a native ed25519-program instruction immediately BEFORE ours in the
//! same transaction; the runtime executes the actual signature check as a
//! precompile (the whole transaction fails if the signature is invalid), and
//! here we introspect the instruction sysvar to prove that the verified
//! (pubkey, message) pair is exactly the one we are recording.

use anchor_lang::prelude::*;
use anchor_lang::solana_program::sysvar::instructions::{
    load_current_index_checked, load_instruction_at_checked,
};

use crate::error::VerifiedInferenceError;

/// Native ed25519 program: Ed25519SigVerify111111111111111111111111111
pub const ED25519_PROGRAM_ID: Pubkey =
    anchor_lang::solana_program::ed25519_program::ID;

/// Byte layout of the ed25519 program instruction data:
///   [0]      num_signatures (u8)
///   [1]      padding (u8)
///   [2..16]  Ed25519SignatureOffsets (7 x u16, little-endian):
///            signature_offset, signature_instruction_index,
///            public_key_offset, public_key_instruction_index,
///            message_data_offset, message_data_size, message_instruction_index
///   [16..]   payload (pubkey, signature, message) at the given offsets
const OFFSETS_START: usize = 2;
const OFFSETS_LEN: usize = 14;

#[inline(always)]
fn read_u16_le(data: &[u8], pos: usize) -> u16 {
    u16::from_le_bytes([data[pos], data[pos + 1]])
}

/// Require that the instruction immediately preceding the current one is a
/// well-formed ed25519-program instruction verifying exactly one signature by
/// `expected_pubkey` over exactly `expected_message`, with all data
/// self-contained in that same instruction (no cross-instruction references).
pub fn require_ed25519_verification(
    instructions_sysvar: &AccountInfo,
    expected_pubkey: &[u8; 32],
    expected_message: &[u8],
) -> Result<()> {
    let current_index = load_current_index_checked(instructions_sysvar)? as usize;
    require!(
        current_index > 0,
        VerifiedInferenceError::MissingEd25519Instruction
    );

    let ed25519_ix_index = current_index - 1;
    let ix = load_instruction_at_checked(ed25519_ix_index, instructions_sysvar)?;

    require_keys_eq!(
        ix.program_id,
        ED25519_PROGRAM_ID,
        VerifiedInferenceError::InvalidEd25519ProgramId
    );
    // The native ed25519 program takes no accounts; anything else is not a
    // plain precompile invocation.
    require!(
        ix.accounts.is_empty(),
        VerifiedInferenceError::MalformedEd25519Instruction
    );

    let data = ix.data.as_slice();
    require!(
        data.len() >= OFFSETS_START + OFFSETS_LEN,
        VerifiedInferenceError::MalformedEd25519Instruction
    );
    require!(
        data[0] == 1,
        VerifiedInferenceError::InvalidEd25519SignatureCount
    );

    let signature_ix_index = read_u16_le(data, OFFSETS_START + 2);
    let public_key_offset = read_u16_le(data, OFFSETS_START + 4) as usize;
    let public_key_ix_index = read_u16_le(data, OFFSETS_START + 6);
    let message_offset = read_u16_le(data, OFFSETS_START + 8) as usize;
    let message_size = read_u16_le(data, OFFSETS_START + 10) as usize;
    let message_ix_index = read_u16_le(data, OFFSETS_START + 12);

    // All three components must live in THIS ed25519 instruction. u16::MAX is
    // the sentinel for "current instruction"; web3.js also emits the explicit
    // index, so accept either — but never a reference to a different
    // instruction, which would let an attacker point at bytes we don't check.
    let this_ix = ed25519_ix_index as u16;
    for idx in [signature_ix_index, public_key_ix_index, message_ix_index] {
        require!(
            idx == u16::MAX || idx == this_ix,
            VerifiedInferenceError::Ed25519CrossInstructionReference
        );
    }

    let pubkey = data
        .get(public_key_offset..public_key_offset + 32)
        .ok_or(VerifiedInferenceError::MalformedEd25519Instruction)?;
    require!(
        pubkey == expected_pubkey,
        VerifiedInferenceError::SignaturePubkeyMismatch
    );

    let message = data
        .get(message_offset..message_offset + message_size)
        .ok_or(VerifiedInferenceError::MalformedEd25519Instruction)?;
    require!(
        message == expected_message,
        VerifiedInferenceError::SignedMessageMismatch
    );

    Ok(())
}
