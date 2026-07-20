import type { LiveLeg } from "@/lib/api";

// Deadpan copy tables. State facts; never grade up.

interface SevLabel {
  label: string;
  detail: string;
}

// metrics.sev_mode: off | sev | es | snp
const SEV_LABELS: Record<string, SevLabel> = {
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
    label: "AMD SEV-SNP",
    detail: "AMD signed the VM launch. See attestation for the verified execution scope.",
  },
};

export function sevLabel(mode: string | null | undefined): SevLabel | null {
  if (!mode) return null;
  return (
    SEV_LABELS[mode] ?? { label: mode, detail: "unrecognized sev_mode value; shown as returned." }
  );
}

// GET /v1/attestation → grade, in plain words. Values: none | launch-only |
// snp. An unrecognized grade is shown as returned.
const GRADE_LABELS: Record<string, string> = {
  none: "no TEE — memory plaintext",
  "launch-only": "SEV memory-encrypted, no runtime report",
  snp: "AMD SEV-SNP report",
};

export function gradeLabel(grade: string | null | undefined): string | null {
  if (!grade) return null;
  return GRADE_LABELS[grade] ?? grade;
}

interface Leg {
  id: LiveLeg;
  label: string;
  desc: string;
}

export const LEGS: Leg[] = [
  {
    id: "A",
    label: "Open-source models without TEE",
    desc: "Runs the open models directly on the AMD host. This is the speed and cost baseline; there is no memory encryption or attestation.",
  },
  {
    id: "B",
    label: "Open-source models in TEE",
    desc: "Runs open models inside AMD SEV-SNP. The browser verifies the attested key before encrypting the prompt and decrypts the response locally.",
  },
  {
    id: "C",
    label: "Claude through TEE proxy",
    desc: "Verifies the proxy, not Claude inference. Anthropic receives the plaintext prompt.",
  },
];

export function legLabel(id: string): string {
  return LEGS.find((item) => item.id === id)?.label ?? id;
}

// Anchor attestation-registry program on devnet; used when the receipt
// carries no per-receipt PDA (the P2 server does not emit one).
export const REGISTRY_PROGRAM = "Dp5LxL9XHZUVXK129rxwBafqHMg1Y29Zda2svx8vXEkx";

export function explorerUrl(address: string): string {
  return `https://explorer.solana.com/address/${address}?cluster=devnet`;
}
