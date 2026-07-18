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
    #[msg("Invalid attestation binding version (expected 1 or 2)")]
    InvalidBindingVersion,
    #[msg("Channel deposit and top-ups must be greater than zero")]
    InvalidChannelAmount,
    #[msg("Channel grace period must be between 60 seconds and 24 hours")]
    InvalidChannelGracePeriod,
    #[msg("Channel is not open for this operation")]
    ChannelNotOpen,
    #[msg("Voucher is expired")]
    VoucherExpired,
    #[msg("Voucher cumulative amount moved backwards")]
    VoucherWentBackwards,
    #[msg("Settlement cumulative amount moved backwards")]
    SettlementWentBackwards,
    #[msg("Settlement exceeds the signed cumulative authorization")]
    SettlementExceedsAuthorization,
    #[msg("Cumulative authorization exceeds the escrowed deposit")]
    AuthorizationExceedsDeposit,
    #[msg("Only the payee, or the payer after the close grace period, may finalize")]
    FinalizeNotAuthorized,
    #[msg("Channel vault balance does not match the recorded deposit")]
    VaultBalanceMismatch,
    #[msg("Arithmetic overflow")]
    ArithmeticOverflow,
}
