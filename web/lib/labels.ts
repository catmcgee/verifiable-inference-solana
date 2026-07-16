// Deadpan copy tables. State facts; never grade up.

export interface SevLabel {
  label: string;
  detail: string;
}

// metrics.sev_mode: off | sev | es | snp
export const SEV_LABELS: Record<string, SevLabel> = {
  off: {
    label: "no TEE",
    detail: "memory in plaintext; nothing attested.",
  },
  sev: {
    label: "SEV: memory encrypted",
    detail: "launch-time memory encryption only; no runtime attestation.",
  },
  es: {
    label: "SEV-ES: memory encrypted",
    detail: "memory and register state encrypted; no runtime attestation.",
  },
  snp: {
    label: "SEV-SNP attested",
    detail: "signed runtime report; verifiable against the AMD key hierarchy.",
  },
};

export function sevLabel(mode: string | null | undefined): SevLabel | null {
  if (!mode) return null;
  return (
    SEV_LABELS[mode] ?? { label: mode, detail: "unrecognized sev_mode value; shown as returned." }
  );
}

// GET /v1/attestation → grade, in plain words. Values: none | launch-only |
// snp | mock. An unrecognized grade is shown as returned.
export const GRADE_LABELS: Record<string, string> = {
  none: "no TEE — memory plaintext",
  "launch-only": "SEV memory-encrypted, no runtime report",
  snp: "SEV-SNP, signed runtime report",
  mock: "dev mock — nothing real",
};

export function gradeLabel(grade: string | null | undefined): string | null {
  if (!grade) return null;
  return GRADE_LABELS[grade] ?? grade;
}

export interface Leg {
  id: string;
  disabled?: boolean;
  desc: string;
}

export const LEGS: Leg[] = [
  {
    id: "A",
    desc: "same box, SEV off. Nothing verifiable; the trust anchor is the operator.",
  },
  {
    id: "B",
    desc: "SEV CVM on the same box. Launch measurement; runtime attestation where SNP.",
  },
  {
    id: "C",
    desc: "attested proxy to the Claude API. The proxy code is verifiable; the inference is not — Anthropic sees plaintext.",
  },
  {
    id: "D",
    disabled: true,
    desc: "ZK proof of inference — deferred until 8×B200 hardware; see report.",
  },
];

// Anchor attestation-registry program on devnet; used when the receipt
// carries no per-receipt PDA (the P2 server does not emit one).
export const REGISTRY_PROGRAM = "Dp5LxL9XHZUVXK129rxwBafqHMg1Y29Zda2svx8vXEkx";

export function explorerUrl(address: string): string {
  return `https://explorer.solana.com/address/${address}?cluster=devnet`;
}
