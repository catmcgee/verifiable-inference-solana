/** Register a live vinfer attestation document on Solana devnet.
 *
 * The attestation must already have been verified by `cli.attest_verify`; this
 * script only anchors its exact binding fields under the enclave-key PDA. It
 * does not invent or post an inference receipt.
 *
 * Usage: node scripts/register-attestation-live.ts <attestation.json>
 */

import * as anchor from "@anchor-lang/core";
import { Program } from "@anchor-lang/core";
import { Connection, Keypair, PublicKey } from "@solana/web3.js";
import * as fs from "fs";
import * as path from "path";
import { createHash } from "crypto";
import { fileURLToPath } from "url";

const DEVNET_URL = "https://api.devnet.solana.com";
const OFF_MEASUREMENT = 0x90;

function canonicalize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, child]) => [key, canonicalize(child)])
    );
  }
  return value;
}

async function main() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const attestationPath = process.argv[2];
  if (!attestationPath) {
    throw new Error(
      "usage: node scripts/register-attestation-live.ts <attestation.json>"
    );
  }
  const att = JSON.parse(fs.readFileSync(attestationPath, "utf8"));
  const enclavePk = Buffer.from(att.enclave_pubkey_b64, "base64");
  if (enclavePk.length !== 32) throw new Error("invalid enclave Ed25519 key");
  if (att.binding_version !== 2)
    throw new Error(
      "only binding_version=2 is supported for live registration"
    );
  if (typeof att.runtime_version !== "string" || !att.runtime_version)
    throw new Error("attestation is missing runtime_version");
  const execution = att.execution ?? {
    mode: "guest-declared",
    manifest: null,
  };
  if (execution.mode === "guest-declared") {
    const runtimeHash = createHash("sha256")
      .update(att.runtime_version)
      .digest("hex");
    if (runtimeHash !== att.server_build_hash)
      throw new Error("runtime_version does not match server_build_hash");
  } else if (execution.mode === "snp-measured-dm-verity") {
    const manifest = execution.manifest;
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest))
      throw new Error("measured execution identity is missing its manifest");
    if (
      manifest.mode !== execution.mode ||
      manifest.runtime_version !== att.runtime_version ||
      manifest.registry_hash !== att.registry_hash
    )
      throw new Error("measured execution manifest does not match attestation");
    const canonicalManifest = JSON.stringify(canonicalize(manifest));
    const manifestHash = createHash("sha256")
      .update(canonicalManifest)
      .digest("hex");
    if (manifestHash !== att.server_build_hash)
      throw new Error(
        "measured execution manifest does not match server_build_hash"
      );
  } else {
    throw new Error(`unsupported execution mode: ${execution.mode}`);
  }

  let grade: any = { noTee: {} };
  let measurement = Buffer.alloc(48);
  if (att.grade === "snp") {
    grade = { snp: {} };
    const report = Buffer.from(att.snp_report_b64, "base64");
    if (report.length < OFF_MEASUREMENT + 48)
      throw new Error("SNP report is too short");
    measurement = report.subarray(OFF_MEASUREMENT, OFF_MEASUREMENT + 48);
  } else if (att.grade === "launch-only") {
    grade = { launchOnly: {} };
  }

  const deployer = Keypair.fromSecretKey(
    Uint8Array.from(
      JSON.parse(
        fs.readFileSync(path.join(here, "..", ".devnet-deployer.json"), "utf8")
      )
    )
  );
  const idl = JSON.parse(
    fs.readFileSync(
      path.join(here, "..", "target", "idl", "verified_inference.json"),
      "utf8"
    )
  );
  const connection = new Connection(DEVNET_URL, "confirmed");
  const provider = new anchor.AnchorProvider(
    connection,
    new anchor.Wallet(deployer),
    { commitment: "confirmed" }
  );
  const program = new Program(idl as any, provider);
  const [attestationPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("attestation"), enclavePk],
    program.programId
  );

  const existing = await connection.getAccountInfo(attestationPda);
  let signature = "already-registered";
  if (!existing) {
    signature = await program.methods
      .registerAttestation({
        enclaveEd25519Pubkey: Array.from(enclavePk),
        snpMeasurement: Array.from(measurement),
        reportDataHash: Array.from(Buffer.from(att.report_data, "hex")),
        // Deprecated for v2. registry_hash covers every hash-bearing entry.
        modelWeightsHash: Array.from(Buffer.alloc(32)),
        runtimeVersion: att.runtime_version,
        attestationGrade: grade,
        bindingVersion: 2,
        registryHash: Array.from(Buffer.from(att.registry_hash, "hex")),
      })
      .accounts({ payer: deployer.publicKey })
      .rpc({ commitment: "confirmed" });
  }

  const account = await (program.account as any).attestationAccount.fetch(
    attestationPda
  );
  if (
    !Buffer.from(account.reportDataHash).equals(
      Buffer.from(att.report_data, "hex")
    )
  )
    throw new Error(
      "on-chain REPORT_DATA differs from the supplied attestation"
    );
  if (
    !Buffer.from(account.registryHash).equals(
      Buffer.from(att.registry_hash, "hex")
    )
  )
    throw new Error(
      "on-chain registry hash differs from the supplied attestation"
    );

  console.log("attestation PDA:", attestationPda.toBase58());
  console.log("register tx    :", signature);
  console.log("grade          :", att.grade);
  console.log("binding        : v2 report_data + registry_hash exact-match");
}

main().then(
  () => process.exit(0),
  (error) => {
    console.error("FAILED:", error);
    process.exit(1);
  }
);
