/**
 * register-live.ts — register a REAL enclave attestation + post a REAL receipt
 * on devnet, from artifacts produced by a live vinfer server (e.g. inside the
 * SNP CVM). Unlike devnet-demo.ts, no key is generated here: the receipt's own
 * ed25519 signature (made inside the enclave) is what the program's
 * instruction-sysvar introspection verifies — the enclave secret never leaves
 * the CVM.
 *
 * Usage: node scripts/register-live.ts <receipt.json>
 *   where receipt.json embeds its attestation doc (server _sign does this).
 */

import * as anchor from "@anchor-lang/core";
import { Program, BN } from "@anchor-lang/core";
import {
  Connection,
  Keypair,
  PublicKey,
  Ed25519Program,
  SYSVAR_INSTRUCTIONS_PUBKEY,
  Transaction,
} from "@solana/web3.js";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";

const DEVNET_URL = "https://api.devnet.solana.com";
const EXPLORER = (kind: "tx" | "address", id: string) =>
  `https://explorer.solana.com/${kind}/${id}?cluster=devnet`;
const u64le = (n: BN | number): Buffer => new BN(n).toArrayLike(Buffer, "le", 8);

// SNP report ABI offsets
const OFF_MEASUREMENT = 0x90; // 48 bytes

async function main() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const receiptPath = process.argv[2];
  if (!receiptPath) throw new Error("usage: node register-live.ts <receipt.json>");
  const receipt = JSON.parse(fs.readFileSync(receiptPath, "utf8"));
  const att = receipt.attestation;
  if (!att) throw new Error("receipt has no embedded attestation doc");

  const enclavePk = Buffer.from(att.enclave_pubkey_b64, "base64");
  if (receipt.enclave_pubkey_b64 !== att.enclave_pubkey_b64)
    throw new Error("receipt/attestation enclave key mismatch");

  // grade → enum variant; SNP measurement from the real report when present
  let grade: any = { noTee: {} };
  let measurement = Buffer.alloc(48);
  if (att.grade === "snp") {
    grade = { snp: {} };
    const report = Buffer.from(att.snp_report_b64, "base64");
    measurement = report.subarray(OFF_MEASUREMENT, OFF_MEASUREMENT + 48);
  } else if (att.grade === "launch-only") {
    grade = { launchOnly: {} };
  }

  const deployer = Keypair.fromSecretKey(
    Uint8Array.from(JSON.parse(fs.readFileSync(path.join(here, "..", ".devnet-deployer.json"), "utf8")))
  );
  const idl = JSON.parse(fs.readFileSync(path.join(here, "..", "target", "idl", "verified_inference.json"), "utf8"));
  const connection = new Connection(DEVNET_URL, "confirmed");
  const provider = new anchor.AnchorProvider(connection, new anchor.Wallet(deployer), { commitment: "confirmed" });
  anchor.setProvider(provider);
  const program = new Program(idl as any, provider);

  const [attestationPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("attestation"), enclavePk], program.programId);

  console.log("enclave pubkey :", enclavePk.toString("hex"));
  console.log("grade          :", att.grade);
  console.log("attestation PDA:", attestationPda.toBase58());

  // 1. register (idempotent per enclave key: skip if PDA exists)
  const existing = await connection.getAccountInfo(attestationPda);
  let regSig = "(already registered)";
  if (!existing) {
    regSig = await program.methods
      .registerAttestation({
        enclaveEd25519Pubkey: Array.from(enclavePk),
        snpMeasurement: Array.from(measurement),
        reportDataHash: Array.from(Buffer.from(att.report_data, "hex")),
        modelWeightsHash: Array.from(Buffer.from(receipt.model_hash, "hex")),
        runtimeVersion: `vinfer@${att.sev_mode}-cvm`,
        attestationGrade: grade,
        bindingVersion: att.binding_version,
        registryHash: Array.from(Buffer.from(att.registry_hash, "hex")),
      })
      .accounts({ payer: deployer.publicKey })
      .rpc({ commitment: "confirmed" });
  }
  console.log("register tx    :", regSig);

  // 2. post the receipt with its REAL in-enclave signature
  const acct = await (program.account as any).attestationAccount.fetch(attestationPda);
  const index = acct.receiptCount.toNumber();
  const [receiptPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("receipt"), enclavePk, u64le(index)], program.programId);
  const msg = Buffer.concat([
    Buffer.from(receipt.prompt_hash, "hex"),
    Buffer.from(receipt.response_hash, "hex"),
    Buffer.from(receipt.model_hash, "hex"),
    new BN(receipt.timestamp).toArrayLike(Buffer, "le", 8),
  ]);
  const ed25519Ix = Ed25519Program.createInstructionWithPublicKey({
    publicKey: new Uint8Array(enclavePk),
    message: new Uint8Array(msg),
    signature: new Uint8Array(Buffer.from(receipt.sig_b64, "base64")),
  });
  const postIx = await program.methods
    .postReceipt(
      Array.from(enclavePk),
      Array.from(Buffer.from(receipt.prompt_hash, "hex")),
      Array.from(Buffer.from(receipt.response_hash, "hex")),
      Array.from(Buffer.from(receipt.model_hash, "hex")),
      new BN(receipt.timestamp),
    )
    .accountsPartial({
      payer: deployer.publicKey,
      attestation: attestationPda,
      receipt: receiptPda,
      instructionsSysvar: SYSVAR_INSTRUCTIONS_PUBKEY,
    })
    .instruction();
  const postSig = await provider.sendAndConfirm(new Transaction().add(ed25519Ix, postIx), [], { commitment: "confirmed" });
  console.log("receipt tx     :", postSig);
  console.log("receipt PDA    :", receiptPda.toBase58(), `(index ${index})`);
  console.log("explorer       :", EXPLORER("address", attestationPda.toBase58()));
}

main().then(() => process.exit(0), (e) => { console.error("FAILED:", e); process.exit(1); });
