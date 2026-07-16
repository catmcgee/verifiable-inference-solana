use anchor_lang::prelude::*;

#[error_code]
pub enum VerifiedInferenceError {
    #[msg("Runtime version string too long (max 64 bytes)")]
    RuntimeVersionTooLong,
    #[msg("No instruction precedes this one; an ed25519-program instruction is required")]
    MissingEd25519Instruction,
    #[msg("Preceding instruction is not the ed25519 program")]
    InvalidEd25519ProgramId,
    #[msg("Ed25519 instruction must carry exactly one signature")]
    InvalidEd25519SignatureCount,
    #[msg("Malformed ed25519 instruction data")]
    MalformedEd25519Instruction,
    #[msg("Ed25519 instruction references data outside itself")]
    Ed25519CrossInstructionReference,
    #[msg("Ed25519 instruction pubkey does not match the registered enclave pubkey")]
    SignaturePubkeyMismatch,
    #[msg("Ed25519 instruction message does not match the canonical receipt message")]
    SignedMessageMismatch,
    #[msg("Batch must contain at least one receipt")]
    EmptyBatch,
    #[msg("Invalid zkML ladder rung id (expected 1..=4)")]
    InvalidRungId,
}
