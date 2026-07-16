import * as anchor from "@anchor-lang/core";
import { Program, BN } from "@anchor-lang/core";
import {
  Ed25519Program,
  PublicKey,
  SYSVAR_INSTRUCTIONS_PUBKEY,
  Transaction,
  TransactionInstruction,
} from "@solana/web3.js";
import nacl from "tweetnacl";
import { assert, expect } from "chai";
import { createHash } from "crypto";
import * as fs from "fs";
import * as path from "path";
import { VerifiedInference } from "../target/types/verified_inference";

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

const sha256 = (data: Buffer): Buffer =>
  createHash("sha256").update(data).digest();

/** prompt_hash || response_hash || model_hash || timestamp_le — the canonical
 *  104-byte single-receipt message the enclave signs. */
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

/** merkle_root || num_receipts_le(u32) || timestamp_le(i64) — canonical
 *  44-byte batch message. */
function batchMessage(root: Buffer, numReceipts: number, timestamp: BN): Buffer {
  const n = Buffer.alloc(4);
  n.writeUInt32LE(numReceipts);
  return Buffer.concat([root, n, timestamp.toArrayLike(Buffer, "le", 8)]);
}

/** sha256 merkle root, lone-leaf promoted (matches state.rs docs). */
function merkleRoot(leaves: Buffer[]): Buffer {
  if (leaves.length === 0) throw new Error("empty merkle tree");
  let level = leaves.map((l) => sha256(l));
  while (level.length > 1) {
    const next: Buffer[] = [];
    for (let i = 0; i < level.length; i += 2) {
      next.push(
        i + 1 < level.length
          ? sha256(Buffer.concat([level[i], level[i + 1]]))
          : level[i] // lone leaf promoted
      );
    }
    level = next;
  }
  return level[0];
}

const u64le = (n: BN | number): Buffer =>
  new BN(n).toArrayLike(Buffer, "le", 8);

// ---------------------------------------------------------------------------
// test suite
// ---------------------------------------------------------------------------

describe("verified_inference", () => {
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);
  const program = anchor.workspace
    .VerifiedInference as Program<VerifiedInference>;
  const connection = provider.connection;

  // The "enclave" signing keypair — in production generated inside the CVM at
  // boot; here a real ed25519 keypair via tweetnacl.
  const enclave = nacl.sign.keyPair();
  const enclavePk = Buffer.from(enclave.publicKey); // 32 bytes
  const unregisteredEnclave = nacl.sign.keyPair();

  const [attestationPda] = PublicKey.findProgramAddressSync(
    [Buffer.from("attestation"), enclavePk],
    program.programId
  );

  const receiptPda = (index: BN | number) =>
    PublicKey.findProgramAddressSync(
      [Buffer.from("receipt"), enclavePk, u64le(index)],
      program.programId
    )[0];

  const batchPda = (index: BN | number) =>
    PublicKey.findProgramAddressSync(
      [Buffer.from("receipt_batch"), enclavePk, u64le(index)],
      program.programId
    )[0];

  // fixture hashes
  const promptHash = sha256(Buffer.from("what is the capital of france?"));
  const responseHash = sha256(Buffer.from("paris"));
  const modelHash = sha256(Buffer.from("bitnet-b1.58-2B4T-weights"));
  const snpMeasurement = Buffer.alloc(48, 7);
  const reportDataHash = sha256(
    Buffer.concat([enclavePk, modelHash, sha256(Buffer.from("server-build"))])
  );

  // CU bookkeeping -----------------------------------------------------------
  const cuLog: { label: string; cu: number; txBytes: number }[] = [];

  async function confirmAndLogCU(label: string, sig: string): Promise<void> {
    const tx = await connection.getTransaction(sig, {
      commitment: "confirmed",
      maxSupportedTransactionVersion: 0,
    });
    assert.isNotNull(tx, `transaction ${sig} not found`);
    const cu = tx!.meta!.computeUnitsConsumed!;
    const txBytes = tx!.transaction.message.serialize().length;
    cuLog.push({ label, cu, txBytes });
    console.log(`      [CU] ${label}: ${cu} CU`);
  }

  /** Send [ed25519 verify ix?, program ix] and return the signature. */
  async function send(
    ixs: TransactionInstruction[],
    label?: string
  ): Promise<string> {
    const tx = new Transaction().add(...ixs);
    const sig = await provider.sendAndConfirm(tx, [], {
      commitment: "confirmed",
    });
    if (label) await confirmAndLogCU(label, sig);
    return sig;
  }

  const ed25519Ix = (
    keypair: nacl.SignKeyPair,
    message: Buffer
  ): TransactionInstruction =>
    Ed25519Program.createInstructionWithPublicKey({
      publicKey: keypair.publicKey,
      message,
      signature: nacl.sign.detached(message, keypair.secretKey),
    });

  const registerIx = (kp: nacl.SignKeyPair) =>
    program.methods
      .registerAttestation({
        enclaveEd25519Pubkey: Array.from(kp.publicKey),
        snpMeasurement: Array.from(snpMeasurement),
        reportDataHash: Array.from(reportDataHash),
        modelWeightsHash: Array.from(modelHash),
        runtimeVersion: "bitnet.cpp@p0-scaffold",
        attestationGrade: { mock: {} },
      })
      .accounts({ payer: provider.wallet.publicKey })
      .instruction();

  const postReceiptIx = (
    kp: nacl.SignKeyPair,
    ts: BN,
    receiptIndex: BN | number,
    pHash: Buffer = promptHash
  ) => {
    const pk = Buffer.from(kp.publicKey);
    const [attPda] = PublicKey.findProgramAddressSync(
      [Buffer.from("attestation"), pk],
      program.programId
    );
    const [rcptPda] = PublicKey.findProgramAddressSync(
      [Buffer.from("receipt"), pk, u64le(receiptIndex)],
      program.programId
    );
    return program.methods
      .postReceipt(
        Array.from(kp.publicKey),
        Array.from(pHash),
        Array.from(responseHash),
        Array.from(modelHash),
        ts
      )
      .accountsPartial({
        payer: provider.wallet.publicKey,
        attestation: attPda,
        receipt: rcptPda,
        instructionsSysvar: SYSVAR_INSTRUCTIONS_PUBKEY,
      })
      .instruction();
  };

  // ---------------------------------------------------------------------------
  // register_attestation
  // ---------------------------------------------------------------------------

  it("registers an attestation (happy path)", async () => {
    const sig = await program.methods
      .registerAttestation({
        enclaveEd25519Pubkey: Array.from(enclave.publicKey),
        snpMeasurement: Array.from(snpMeasurement),
        reportDataHash: Array.from(reportDataHash),
        modelWeightsHash: Array.from(modelHash),
        runtimeVersion: "bitnet.cpp@p0-scaffold",
        attestationGrade: { mock: {} },
      })
      .accounts({ payer: provider.wallet.publicKey })
      .rpc({ commitment: "confirmed" });
    await confirmAndLogCU("register_attestation", sig);

    const att = await program.account.attestationAccount.fetch(attestationPda);
    expect(Buffer.from(att.enclaveEd25519Pubkey)).to.deep.equal(enclavePk);
    expect(Buffer.from(att.snpMeasurement)).to.deep.equal(snpMeasurement);
    expect(Buffer.from(att.reportDataHash)).to.deep.equal(reportDataHash);
    expect(Buffer.from(att.modelWeightsHash)).to.deep.equal(modelHash);
    expect(att.runtimeVersion).to.equal("bitnet.cpp@p0-scaffold");
    expect(att.attestationGrade).to.deep.equal({ mock: {} });
    expect(att.slot.toNumber()).to.be.greaterThan(0);
    expect(att.receiptCount.toNumber()).to.equal(0);
    expect(att.batchCount.toNumber()).to.equal(0);
  });

  it("fails to re-register the same enclave pubkey", async () => {
    try {
      await program.methods
        .registerAttestation({
          enclaveEd25519Pubkey: Array.from(enclave.publicKey),
          snpMeasurement: Array.from(snpMeasurement),
          reportDataHash: Array.from(reportDataHash),
          modelWeightsHash: Array.from(modelHash),
          runtimeVersion: "bitnet.cpp@p0-scaffold-reboot",
          attestationGrade: { snp: {} },
        })
        .accounts({ payer: provider.wallet.publicKey })
        .rpc({ commitment: "confirmed" });
      assert.fail("duplicate registration should have failed");
    } catch (err: any) {
      // `init` on an existing PDA -> SystemProgram "account already in use"
      const s = err.toString() + JSON.stringify(err.logs ?? []);
      assert.match(s, /already in use|custom program error: 0x0/i);
    }
    // original registration untouched
    const att = await program.account.attestationAccount.fetch(attestationPda);
    expect(att.runtimeVersion).to.equal("bitnet.cpp@p0-scaffold");
  });

  // ---------------------------------------------------------------------------
  // post_receipt
  // ---------------------------------------------------------------------------

  it("posts a signed receipt (happy path)", async () => {
    const ts = new BN(Math.floor(Date.now() / 1000));
    const msg = receiptMessage(promptHash, responseHash, modelHash, ts);
    await send(
      [ed25519Ix(enclave, msg), await postReceiptIx(enclave, ts, 0)],
      "post_receipt (ed25519 + program ix)"
    );

    const rcpt = await program.account.receiptAccount.fetch(receiptPda(0));
    expect(Buffer.from(rcpt.enclaveEd25519Pubkey)).to.deep.equal(enclavePk);
    expect(Buffer.from(rcpt.promptHash)).to.deep.equal(promptHash);
    expect(Buffer.from(rcpt.responseHash)).to.deep.equal(responseHash);
    expect(Buffer.from(rcpt.modelHash)).to.deep.equal(modelHash);
    expect(rcpt.timestamp.eq(ts)).to.be.true;
    expect(rcpt.index.toNumber()).to.equal(0);

    const att = await program.account.attestationAccount.fetch(attestationPda);
    expect(att.receiptCount.toNumber()).to.equal(1);
  });

  it("fails post_receipt without a preceding ed25519 instruction", async () => {
    const ts = new BN(Math.floor(Date.now() / 1000));
    try {
      await send([await postReceiptIx(enclave, ts, 1)]);
      assert.fail("should have failed: no ed25519 instruction");
    } catch (err: any) {
      assert.match(err.toString(), /MissingEd25519Instruction/);
    }
  });

  it("fails post_receipt when the ed25519 instruction is for a different pubkey", async () => {
    // Valid signature by an imposter key over the correct message: the
    // precompile passes, but introspection must reject the pubkey mismatch.
    const ts = new BN(Math.floor(Date.now() / 1000));
    const msg = receiptMessage(promptHash, responseHash, modelHash, ts);
    const imposter = nacl.sign.keyPair();
    try {
      await send([
        ed25519Ix(imposter, msg),
        await postReceiptIx(enclave, ts, 1),
      ]);
      assert.fail("should have failed: pubkey mismatch");
    } catch (err: any) {
      assert.match(err.toString(), /SignaturePubkeyMismatch/);
    }
  });

  it("fails post_receipt when the signed message differs from the recorded fields", async () => {
    const ts = new BN(Math.floor(Date.now() / 1000));
    const tampered = receiptMessage(
      sha256(Buffer.from("some other prompt")),
      responseHash,
      modelHash,
      ts
    );
    try {
      await send([
        ed25519Ix(enclave, tampered),
        await postReceiptIx(enclave, ts, 1),
      ]);
      assert.fail("should have failed: message mismatch");
    } catch (err: any) {
      assert.match(err.toString(), /SignedMessageMismatch/);
    }
  });

  it("fails post_receipt with a corrupted signature (precompile rejects the tx)", async () => {
    const ts = new BN(Math.floor(Date.now() / 1000));
    const msg = receiptMessage(promptHash, responseHash, modelHash, ts);
    const sig = nacl.sign.detached(msg, enclave.secretKey);
    sig[0] ^= 0xff; // corrupt
    const badIx = Ed25519Program.createInstructionWithPublicKey({
      publicKey: enclave.publicKey,
      message: msg,
      signature: sig,
    });
    try {
      await send([badIx, await postReceiptIx(enclave, ts, 1)]);
      assert.fail("should have failed: invalid ed25519 signature");
    } catch (err: any) {
      // Rejected by the runtime before our program runs.
      assert.match(err.toString(), /precompile|signature|SendTransactionError/i);
    }
  });

  it("fails post_receipt from an unregistered enclave", async () => {
    const ts = new BN(Math.floor(Date.now() / 1000));
    const msg = receiptMessage(promptHash, responseHash, modelHash, ts);
    try {
      await send([
        ed25519Ix(unregisteredEnclave, msg),
        await postReceiptIx(unregisteredEnclave, ts, 0),
      ]);
      assert.fail("should have failed: unregistered enclave");
    } catch (err: any) {
      assert.match(err.toString(), /AccountNotInitialized/);
    }
  });

  it("posts a second receipt (counter advances, CU steady-state)", async () => {
    const ts = new BN(Math.floor(Date.now() / 1000));
    const msg = receiptMessage(promptHash, responseHash, modelHash, ts);
    await send(
      [ed25519Ix(enclave, msg), await postReceiptIx(enclave, ts, 1)],
      "post_receipt (2nd, steady-state)"
    );
    const rcpt = await program.account.receiptAccount.fetch(receiptPda(1));
    expect(rcpt.index.toNumber()).to.equal(1);
  });

  // ---------------------------------------------------------------------------
  // post_receipt_batch
  // ---------------------------------------------------------------------------

  const BATCH_N = 32;

  it(`posts a merkle-batched receipt root (${BATCH_N} receipts, one signature)`, async () => {
    const ts = new BN(Math.floor(Date.now() / 1000));
    const leaves: Buffer[] = [];
    for (let i = 0; i < BATCH_N; i++) {
      leaves.push(
        receiptMessage(
          sha256(Buffer.from(`prompt-${i}`)),
          sha256(Buffer.from(`response-${i}`)),
          modelHash,
          ts
        )
      );
    }
    const root = merkleRoot(leaves);
    const msg = batchMessage(root, BATCH_N, ts);

    const ix = await program.methods
      .postReceiptBatch(
        Array.from(enclave.publicKey),
        Array.from(root),
        BATCH_N,
        ts
      )
      .accountsPartial({
        payer: provider.wallet.publicKey,
        attestation: attestationPda,
        batch: batchPda(0),
        instructionsSysvar: SYSVAR_INSTRUCTIONS_PUBKEY,
      })
      .instruction();
    await send(
      [ed25519Ix(enclave, msg), ix],
      `post_receipt_batch (${BATCH_N} receipts)`
    );

    const batch = await program.account.receiptBatchAccount.fetch(batchPda(0));
    expect(Buffer.from(batch.merkleRoot)).to.deep.equal(root);
    expect(batch.numReceipts).to.equal(BATCH_N);
    expect(batch.index.toNumber()).to.equal(0);
    const att = await program.account.attestationAccount.fetch(attestationPda);
    expect(att.batchCount.toNumber()).to.equal(1);
  });

  // ---------------------------------------------------------------------------
  // verify_inference_proof (stub)
  // ---------------------------------------------------------------------------

  it("records a zkML proof commitment (stub — no verification yet)", async () => {
    const proofHash = sha256(Buffer.from("groth16-proof-bytes-placeholder"));
    const publicInputsHash = sha256(Buffer.from("public-inputs-placeholder"));
    const [proofPda] = PublicKey.findProgramAddressSync(
      [Buffer.from("proof"), proofHash],
      program.programId
    );

    const sig = await program.methods
      .verifyInferenceProof(
        Array.from(proofHash),
        Array.from(publicInputsHash),
        1 // ladder rung 1: one ternary matmul
      )
      .accounts({ payer: provider.wallet.publicKey })
      .rpc({ commitment: "confirmed" });
    await confirmAndLogCU("verify_inference_proof (stub)", sig);

    const rec = await program.account.proofRecordAccount.fetch(proofPda);
    expect(Buffer.from(rec.proofHash)).to.deep.equal(proofHash);
    expect(Buffer.from(rec.publicInputsHash)).to.deep.equal(publicInputsHash);
    expect(rec.rungId).to.equal(1);
    // TODO(groth16): stays false until real alt_bn128 verification lands.
    expect(rec.verified).to.be.false;
  });

  it("rejects an out-of-range rung id", async () => {
    const proofHash = sha256(Buffer.from("another-proof"));
    try {
      await program.methods
        .verifyInferenceProof(
          Array.from(proofHash),
          Array.from(sha256(Buffer.from("pi"))),
          9
        )
        .accounts({ payer: provider.wallet.publicKey })
        .rpc({ commitment: "confirmed" });
      assert.fail("should have failed: bad rung id");
    } catch (err: any) {
      assert.match(err.toString(), /InvalidRungId/);
    }
  });

  // ---------------------------------------------------------------------------
  // CU notes
  // ---------------------------------------------------------------------------

  after(() => {
    if (cuLog.length === 0) return;
    console.log("\n  Compute units consumed (localnet):");
    for (const { label, cu, txBytes } of cuLog) {
      console.log(`    ${label.padEnd(42)} ${String(cu).padStart(7)} CU  (tx msg ${txBytes} B)`);
    }
    const perReceiptBatch = cuLog.find((e) =>
      e.label.startsWith("post_receipt_batch")
    );
    const single = cuLog.find((e) => e.label.startsWith("post_receipt ("));
    if (perReceiptBatch && single) {
      console.log(
        `    -> batched: ${(perReceiptBatch.cu / BATCH_N).toFixed(1)} CU per receipt ` +
          `vs ${single.cu} CU single (${(
            single.cu /
            (perReceiptBatch.cu / BATCH_N)
          ).toFixed(1)}x cheaper per receipt, program CU only)`
      );
    }

    // Refresh the measured table in solana/CU-NOTES.md between markers.
    const notesPath = path.join(__dirname, "..", "CU-NOTES.md");
    if (fs.existsSync(notesPath)) {
      const begin = "<!-- CU:BEGIN (auto-generated by anchor test) -->";
      const end = "<!-- CU:END -->";
      const table = [
        begin,
        "",
        `Measured ${new Date().toISOString()} on localnet (anchor test).`,
        "",
        "| instruction | CU consumed | tx message bytes |",
        "|---|---|---|",
        ...cuLog.map((e) => `| ${e.label} | ${e.cu} | ${e.txBytes} |`),
        ...(perReceiptBatch && single
          ? [
              "",
              `Batched amortization: ${BATCH_N} receipts in one batch -> ` +
                `${(perReceiptBatch.cu / BATCH_N).toFixed(1)} CU/receipt vs ` +
                `${single.cu} CU for a single post_receipt.`,
            ]
          : []),
        "",
        end,
      ].join("\n");
      const cur = fs.readFileSync(notesPath, "utf8");
      const b = cur.indexOf(begin);
      const e = cur.indexOf(end);
      if (b !== -1 && e !== -1) {
        fs.writeFileSync(
          notesPath,
          cur.slice(0, b) + table + cur.slice(e + end.length)
        );
      }
    }
  });
});
