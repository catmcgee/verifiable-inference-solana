/**
 * devnet-demo.ts — exercise the deployed `verified_inference` program on
 * Solana DEVNET with real transactions, so the receipt-verification pipeline
 * has live devnet records.
 *
 * What it does (all against devnet):
 *   1. generates a fresh "enclave" ed25519 keypair (tweetnacl) — in production
 *      this is generated inside the CVM at boot.
 *   2. register_attestation with binding_version = 2 and a sample registry_hash.
 *   3. post_receipt with a real native ed25519-program instruction placed
 *      immediately before the program instruction (the program introspects the
 *      instruction sysvar to bind the verified pubkey+message).
 *
 * Prints: all tx signatures, the attestation + receipt PDAs, measured devnet
 * compute units (from tx meta), and Solana Explorer URLs (?cluster=devnet).
 *
 * Run:  node scripts/devnet-demo.ts        (Node >= 23.6 strips TS types)
 * Requires: solana/.devnet-deployer.json funded on devnet (payer/fee-payer).
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
  TransactionInstruction,
} from "@solana/web3.js";
import nacl from "tweetnacl";
import { createHash } from "crypto";
import * as fs from "fs";
import * as path from "path";

const DEVNET_URL = "https://api.devnet.solana.com";
const EXPLORER = (kind: "tx" | "address", id: string) =>
  `https://explorer.solana.com/${kind}/${id}?cluster=devnet`;

const sha256 = (data: Buffer): Buffer =>
  createHash("sha256").update(data).digest();

const u64le = (n: BN | number): Buffer =>
  new BN(n).toArrayLike(Buffer, "le", 8);

/** prompt_hash || response_hash || model_hash || timestamp_le (104 bytes). */
function receiptMessage(
  promptHash: Buffer,
  responseHash: Buffer,
  modelHash: Buffer,
  timestamp: BN
): Buffer {
  return Buffer.concat([
    promptHash,
    responseHash,
    modelHash,
    timestamp.toArrayLike(Buffer, "le", 8),
  ]);
}

async function main() {
  const here = __dirname;
  const deployerPath = path.join(here, "..", ".devnet-deployer.json");
  const idlPath = path.join(here, "..", "target", "idl", "verified_inference.json");

  const deployer = Keypair.fromSecretKey(
    Uint8Array.from(JSON.parse(fs.readFileSync(deployerPath, "utf8")))
  );
  const idl = JSON.parse(fs.readFileSync(idlPath, "utf8"));

  const connection = new Connection(DEVNET_URL, "confirmed");
  const wallet = new anchor.Wallet(deployer);
  const provider = new anchor.AnchorProvider(connection, wallet, {
    commitment: "confirmed",
  });
  anchor.setProvider(provider);
  const program = new Program(idl as any, provider);

  const bal = await connection.getBalance(deployer.publicKey);
  console.log("=".repeat(72));
  console.log("verified_inference — DEVNET demo");
  console.log("=".repeat(72));
  console.log("program id      :", program.programId.toBase58());
  console.log("payer (deployer):", deployer.publicKey.toBase58());
  console.log("payer balance   :", (bal / 1e9).toFixed(4), "SOL");
  console.log("");

  // --- enclave keypair (generated inside the CVM in production) --------------
  const enclave = nacl.sign.keyPair();
  const enclavePk = Buffer.from(enclave.publicKey); // 32 bytes
  console.log("enclave ed25519 pubkey:", Buffer.from(enclavePk).toString("hex"));

  // fixture hashes
  const modelHash = sha256(Buffer.from("bitnet-b1.58-2B4T-weights"));
  const promptHash = sha256(Buffer.from("what is the capital of france?"));
  const responseHash = sha256(Buffer.from("paris"));
  const snpMeasurement = Buffer.alloc(48, 7);
  // Binding v2: registry_hash = sha256 over sorted (model_id, weights_sha256).
  const registryHash = sha256(
    Buffer.from(`bitnet-b1.58-2b4t:${modelHash.toString("hex")}`)
  );
  // v2 REPORT_DATA binds the registry hash, not a single model hash.
  const reportDataHash = sha256(
    Buffer.concat([enclavePk, registryHash, sha256(Buffer.from("server-build"))])
  );

  const [attestationPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("attestation"), enclavePk],
    program.programId
  );
  const [receiptPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("receipt"), enclavePk, u64le(0)],
    program.programId
  );
  console.log("attestation PDA :", attestationPda.toBase58());
  console.log("receipt[0] PDA  :", receiptPda.toBase58());
  console.log("");

  const cuOf = async (sig: string): Promise<number | null> => {
    const tx = await connection.getTransaction(sig, {
      commitment: "confirmed",
      maxSupportedTransactionVersion: 0,
    });
    return tx?.meta?.computeUnitsConsumed ?? null;
  };

  const results: any = {
    programId: program.programId.toBase58(),
    deployerPubkey: deployer.publicKey.toBase58(),
    enclavePubkeyHex: Buffer.from(enclavePk).toString("hex"),
    attestationPda: attestationPda.toBase58(),
    receiptPda: receiptPda.toBase58(),
    registryHashHex: registryHash.toString("hex"),
  };

  // --- 1. register_attestation (binding v2) ---------------------------------
  console.log("[1/2] register_attestation (binding_version=2) ...");
  const regSig = await program.methods
    .registerAttestation({
      enclaveEd25519Pubkey: Array.from(enclave.publicKey),
      snpMeasurement: Array.from(snpMeasurement),
      reportDataHash: Array.from(reportDataHash),
      modelWeightsHash: Array.from(modelHash),
      runtimeVersion: "bitnet.cpp@devnet-demo",
      attestationGrade: { mock: {} },
      bindingVersion: 2,
      registryHash: Array.from(registryHash),
    })
    .accounts({ payer: deployer.publicKey })
    .rpc({ commitment: "confirmed" });
  const regCu = await cuOf(regSig);
  results.registerAttestation = { sig: regSig, cu: regCu };
  console.log("      sig:", regSig);
  console.log("      CU :", regCu);
  console.log("      url:", EXPLORER("tx", regSig));

  const att = await (program.account as any).attestationAccount.fetch(
    attestationPda
  );
  console.log(
    "      on-chain: bindingVersion=%d receiptCount=%d slot=%s",
    att.bindingVersion,
    att.receiptCount.toNumber(),
    att.slot.toString()
  );
  console.log("");

  // --- 2. post_receipt (ed25519 verify ix + program ix) ---------------------
  console.log("[2/2] post_receipt (native ed25519 ix + program ix) ...");
  const ts = new BN(Math.floor(Date.now() / 1000));
  const msg = receiptMessage(promptHash, responseHash, modelHash, ts);
  const ed25519Ix: TransactionInstruction =
    Ed25519Program.createInstructionWithPublicKey({
      publicKey: enclave.publicKey,
      message: msg,
      signature: nacl.sign.detached(msg, enclave.secretKey),
    });
  const postIx = await program.methods
    .postReceipt(
      Array.from(enclave.publicKey),
      Array.from(promptHash),
      Array.from(responseHash),
      Array.from(modelHash),
      ts
    )
    .accountsPartial({
      payer: deployer.publicKey,
      attestation: attestationPda,
      receipt: receiptPda,
      instructionsSysvar: SYSVAR_INSTRUCTIONS_PUBKEY,
    })
    .instruction();

  const tx = new Transaction().add(ed25519Ix, postIx);
  const postSig = await provider.sendAndConfirm(tx, [], {
    commitment: "confirmed",
  });
  const postCu = await cuOf(postSig);
  results.postReceipt = { sig: postSig, cu: postCu };
  console.log("      sig:", postSig);
  console.log("      CU :", postCu, "(ed25519 precompile + program ix)");
  console.log("      url:", EXPLORER("tx", postSig));

  const rcpt = await (program.account as any).receiptAccount.fetch(receiptPda);
  console.log(
    "      on-chain: receipt index=%d timestamp=%s slot=%s",
    rcpt.index.toNumber(),
    rcpt.timestamp.toString(),
    rcpt.slot.toString()
  );
  console.log("");

  console.log("=".repeat(72));
  console.log("Explorer links");
  console.log("=".repeat(72));
  console.log("program      :", EXPLORER("address", results.programId));
  console.log("attestation  :", EXPLORER("address", results.attestationPda));
  console.log("receipt[0]   :", EXPLORER("address", results.receiptPda));
  console.log("register tx  :", EXPLORER("tx", results.registerAttestation.sig));
  console.log("receipt tx   :", EXPLORER("tx", results.postReceipt.sig));
  console.log("");

  // Emit a machine-readable summary (stdout only) for DEVNET-NOTES.md.
  console.log("JSON_RESULT_BEGIN");
  console.log(JSON.stringify(results));
  console.log("JSON_RESULT_END");
}

main().then(
  () => process.exit(0),
  (err) => {
    console.error("devnet-demo FAILED:", err);
    process.exit(1);
  }
);
