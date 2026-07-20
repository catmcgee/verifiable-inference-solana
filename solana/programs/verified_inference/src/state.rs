use anchor_lang::prelude::*;

/// What the on-chain registry entry can actually claim about the enclave.
/// If recon finds plain SEV without SNP, the
/// entry is LaunchOnly and the report documents what that does NOT prove.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, Debug, InitSpace)]
pub enum AttestationGrade {
    /// Full SEV-SNP: signed runtime report binding the enclave key + model hash.
    Snp,
    /// Plain SEV / SEV-ES: launch-time measurement only, no signed runtime report.
    LaunchOnly,
    /// No TEE: the enclave key was generated with plaintext memory (e.g. on bare
    /// metal or a laptop). The receipt still cryptographically binds model + I/O
    /// to the key, but a verifier can conclude nothing about confidentiality.
    /// This is the honest grade for the devnet pipeline demo — there is no "mock".
    NoTee,
}

/// One per CVM boot, keyed by the enclave's ed25519 signing pubkey.
/// PDA seeds: ["attestation", enclave_ed25519_pubkey]
#[account]
#[derive(InitSpace)]
pub struct AttestationAccount {
    /// Enclave signing key generated inside the CVM at boot (never persisted outside).
    pub enclave_ed25519_pubkey: [u8; 32],
    /// SNP launch measurement (48 bytes). Zeroed for LaunchOnly/NoTee grades.
    pub snp_measurement: [u8; 48],
    /// REPORT_DATA hash as embedded in the SNP report:
    /// v1: hash(enclave_ed25519_pubkey || model_weights_hash || server_build_hash)
    /// v2: hash(enclave_ed25519_pubkey || registry_hash || server_build_hash)
    pub report_data_hash: [u8; 32],
    /// Hash of the model weights served by this enclave (v1 binding; kept for
    /// backward compat — v2 registrations may still fill it for a single model).
    pub model_weights_hash: [u8; 32],
    /// Attestation binding scheme: 1 = legacy single-model-hash binding,
    /// 2 = registry-hash binding (see the attestation binding v2 verifier).
    pub binding_version: u8,
    /// v2 only: sha256 over sorted (model_id, weights_sha256) pairs of the
    /// model registry this enclave serves. Zeroed for v1 registrations.
    pub registry_hash: [u8; 32],
    /// Short runtime version string, e.g. "bitnet.cpp@a1b2c3".
    #[max_len(64)]
    pub runtime_version: String,
    pub attestation_grade: AttestationGrade,
    /// Slot at registration time.
    pub slot: u64,
    /// Monotonic counter: next receipt index for this enclave (also PDA seed).
    pub receipt_count: u64,
    /// Reserved for compatibility with accounts created by program v0.1.
    pub reserved: u64,
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
