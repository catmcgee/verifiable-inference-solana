use anchor_lang::prelude::*;

/// What the on-chain registry entry can actually claim about the enclave.
/// See PLAN.md "Attestation (leg B)": if recon says plain SEV (no SNP), the
/// entry is LaunchOnly and the report documents what that does NOT prove.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, Debug, InitSpace)]
pub enum AttestationGrade {
    /// Full SEV-SNP: signed runtime report binding the enclave key + model hash.
    Snp,
    /// Plain SEV / SEV-ES: launch-time measurement only, no signed runtime report.
    LaunchOnly,
    /// Local/mock testing (P0 scaffold, localnet).
    Mock,
}

/// One per CVM boot, keyed by the enclave's ed25519 signing pubkey.
/// PDA seeds: ["attestation", enclave_ed25519_pubkey]
#[account]
#[derive(InitSpace)]
pub struct AttestationAccount {
    /// Enclave signing key generated inside the CVM at boot (never persisted outside).
    pub enclave_ed25519_pubkey: [u8; 32],
    /// SNP launch measurement (48 bytes). Zeroed for LaunchOnly/Mock grades.
    pub snp_measurement: [u8; 48],
    /// hash(enclave_ed25519_pubkey || model_weights_hash || server_build_hash)
    /// as embedded in the SNP report's REPORT_DATA field.
    pub report_data_hash: [u8; 32],
    /// Hash of the model weights served by this enclave.
    pub model_weights_hash: [u8; 32],
    /// Short runtime version string, e.g. "bitnet.cpp@a1b2c3".
    #[max_len(64)]
    pub runtime_version: String,
    pub attestation_grade: AttestationGrade,
    /// Slot at registration time.
    pub slot: u64,
    /// Monotonic counter: next receipt index for this enclave (also PDA seed).
    pub receipt_count: u64,
    /// Monotonic counter: next receipt batch index for this enclave (also PDA seed).
    pub batch_count: u64,
    pub bump: u8,
}

/// One signed inference receipt.
/// PDA seeds: ["receipt", enclave_ed25519_pubkey, receipt_index_le]
///
/// The ed25519 signature verified by the preceding ed25519-program instruction
/// covers exactly: prompt_hash || response_hash || model_hash || timestamp_le (104 bytes).
#[account]
#[derive(InitSpace)]
pub struct ReceiptAccount {
    pub enclave_ed25519_pubkey: [u8; 32],
    pub prompt_hash: [u8; 32],
    pub response_hash: [u8; 32],
    pub model_hash: [u8; 32],
    /// Enclave-reported unix timestamp (part of the signed message).
    pub timestamp: i64,
    /// Index of this receipt for the enclave (PDA seed).
    pub index: u64,
    /// Slot at posting time.
    pub slot: u64,
    pub bump: u8,
}

/// Merkle-batched receipts: one signature check amortized over N receipts.
/// PDA seeds: ["receipt_batch", enclave_ed25519_pubkey, batch_index_le]
///
/// Signed message: merkle_root || num_receipts_le(u32) || timestamp_le(i64) (44 bytes).
/// Leaves are the 104-byte single-receipt messages hashed with SHA-256; inner
/// nodes sha256(left || right) with lone-leaf promotion (off-chain convention;
/// inclusion proofs are verified off-chain by `vinfer verify`).
#[account]
#[derive(InitSpace)]
pub struct ReceiptBatchAccount {
    pub enclave_ed25519_pubkey: [u8; 32],
    pub merkle_root: [u8; 32],
    pub num_receipts: u32,
    pub timestamp: i64,
    /// Index of this batch for the enclave (PDA seed).
    pub index: u64,
    pub slot: u64,
    pub bump: u8,
}

/// Leg D (zkML) proof record.
/// PDA seeds: ["proof", proof_hash]
///
/// TODO(groth16): this is a stub. In P3/P4 wire Light Protocol's
/// groth16-solana (alt_bn128 syscalls) and verify the actual proof on-chain;
/// `verified` stays false until then.
#[account]
#[derive(InitSpace)]
pub struct ProofRecordAccount {
    pub proof_hash: [u8; 32],
    pub public_inputs_hash: [u8; 32],
    /// Which rung of the zkML ladder this proof covers (1..=4, see PLAN.md).
    pub rung_id: u8,
    /// Always false in the stub. Set true only by real Groth16 verification.
    pub verified: bool,
    pub slot: u64,
    pub bump: u8,
}
