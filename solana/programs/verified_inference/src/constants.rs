use anchor_lang::prelude::*;

#[constant]
pub const ATTESTATION_SEED: &[u8] = b"attestation";

#[constant]
pub const RECEIPT_SEED: &[u8] = b"receipt";

#[constant]
pub const RECEIPT_BATCH_SEED: &[u8] = b"receipt_batch";

#[constant]
pub const PROOF_SEED: &[u8] = b"proof";

#[constant]
pub const CHANNEL_SEED: &[u8] = b"channel";

#[constant]
pub const CHANNEL_VAULT_SEED: &[u8] = b"channel_vault";

/// Max length of the runtime_version string (bytes).
#[constant]
pub const MAX_RUNTIME_VERSION_LEN: u8 = 64;

/// Canonical single-receipt signed message length:
/// prompt_hash(32) || response_hash(32) || model_hash(32) || timestamp_le(8)
pub const RECEIPT_MSG_LEN: usize = 104;

/// Canonical batch signed message length:
/// merkle_root(32) || num_receipts_le(4) || timestamp_le(8)
pub const BATCH_MSG_LEN: usize = 44;

/// channel_pubkey(32) || cumulative_authorized_le(8) || expires_at_le(8)
pub const CHANNEL_VOUCHER_MSG_LEN: usize = 48;

pub const MIN_CHANNEL_GRACE_SECONDS: u32 = 60;
pub const MAX_CHANNEL_GRACE_SECONDS: u32 = 86_400;
