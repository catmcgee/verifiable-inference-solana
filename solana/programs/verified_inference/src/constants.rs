use anchor_lang::prelude::*;

#[constant]
pub const ATTESTATION_SEED: &[u8] = b"attestation";

#[constant]
pub const RECEIPT_SEED: &[u8] = b"receipt";

/// Max length of the runtime_version string (bytes).
#[constant]
pub const MAX_RUNTIME_VERSION_LEN: u8 = 64;

/// Canonical single-receipt signed message length:
/// prompt_hash(32) || response_hash(32) || model_hash(32) || timestamp_le(8)
pub const RECEIPT_MSG_LEN: usize = 104;
