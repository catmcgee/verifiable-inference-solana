import * as anchor from "@anchor-lang/core";
import { Program, BN } from "@anchor-lang/core";
import {
  Ed25519Program,
  LAMPORTS_PER_SOL,
  PublicKey,
  SYSVAR_INSTRUCTIONS_PUBKEY,
  Transaction,
  TransactionInstruction,
} from "@solana/web3.js";
import nacl from "tweetnacl";
import { assert, expect } from "chai";
import { createHash } from "crypto";
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

  before(async () => {
    const endpoint = connection.rpcEndpoint;
    if (!endpoint.includes("127.0.0.1") && !endpoint.includes("localhost")) {
      throw new Error(
        `tests require localnet; refusing RPC endpoint ${endpoint}`
      );
    }
    const minimumBalance = 5 * LAMPORTS_PER_SOL;
    if (
      (await connection.getBalance(provider.wallet.publicKey)) >= minimumBalance
    ) {
      return;
    }
    const signature = await connection.requestAirdrop(
      provider.wallet.publicKey,
      10 * LAMPORTS_PER_SOL
    );
    const latest = await connection.getLatestBlockhash();
    await connection.confirmTransaction({ signature, ...latest }, "confirmed");
  });

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

  // fixture hashes
  const promptHash = sha256(Buffer.from("what is the capital of france?"));
  const responseHash = sha256(Buffer.from("paris"));
  const modelHash = sha256(Buffer.from("bitnet-b1.58-2B4T-weights"));
  const snpMeasurement = Buffer.alloc(48, 7);
  // Binding v2: registry_hash = sha256 over sorted (model_id, weights_sha256)
  // pairs used by attestation binding v2. Single-model registry here.
  const registryHash = sha256(
    Buffer.from(`bitnet-b1.58-2b4t:${modelHash.toString("hex")}`)
  );
  // v2 REPORT_DATA binds the registry hash, not a single model hash.
  const reportDataHash = sha256(
    Buffer.concat([
      enclavePk,
      registryHash,
      sha256(Buffer.from("server-build")),
    ])
  );
  const zeroRegistryHash = Buffer.alloc(32, 0);

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

  it("exposes a hash-only receipt instruction and account schema", () => {
    const idl = program.idl as any;
    const instruction = idl.instructions.find(
      (item: any) => item.name === "postReceipt"
    );
    expect(instruction.args.map((arg: any) => arg.name)).to.deep.equal([
      "enclaveEd25519Pubkey",
      "promptHash",
      "responseHash",
      "modelHash",
      "timestamp",
    ]);
    for (const argument of instruction.args.slice(0, 4)) {
      expect(argument.type).to.deep.equal({ array: ["u8", 32] });
    }

    const receipt = idl.types.find(
      (item: any) => item.name === "receiptAccount"
    );
    const fields = receipt.type.fields.map((field: any) => field.name);
    expect(fields).to.deep.equal([
      "enclaveEd25519Pubkey",
      "promptHash",
      "responseHash",
      "modelHash",
      "timestamp",
      "index",
      "slot",
      "bump",
    ]);
    expect(fields).not.to.include.members([
      "prompt",
      "response",
      "messages",
      "user",
    ]);
  });

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

  it("registers a v2 (registry-hash binding) attestation (happy path)", async () => {
    const sig = await program.methods
      .registerAttestation({
        enclaveEd25519Pubkey: Array.from(enclave.publicKey),
        snpMeasurement: Array.from(snpMeasurement),
        reportDataHash: Array.from(reportDataHash),
        modelWeightsHash: Array.from(modelHash),
        runtimeVersion: "bitnet.cpp@p0-scaffold",
        attestationGrade: { noTee: {} },
        bindingVersion: 2,
        registryHash: Array.from(registryHash),
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
    expect(att.attestationGrade).to.deep.equal({ noTee: {} });
    expect(att.bindingVersion).to.equal(2);
    expect(Buffer.from(att.registryHash)).to.deep.equal(registryHash);
    expect(att.slot.toNumber()).to.be.greaterThan(0);
    expect(att.receiptCount.toNumber()).to.equal(0);
    expect(att.reserved.toNumber()).to.equal(0);
  });

  it("registers a v1 (legacy model-hash binding) attestation", async () => {
    const v1Enclave = nacl.sign.keyPair();
    const v1Pk = Buffer.from(v1Enclave.publicKey);
    const [v1Pda] = PublicKey.findProgramAddressSync(
      [Buffer.from("attestation"), v1Pk],
      program.programId
    );
    // v1 REPORT_DATA binds the single model hash; registry_hash is zeroed.
    const v1ReportDataHash = sha256(
      Buffer.concat([v1Pk, modelHash, sha256(Buffer.from("server-build"))])
    );
    await program.methods
      .registerAttestation({
        enclaveEd25519Pubkey: Array.from(v1Enclave.publicKey),
        snpMeasurement: Array.from(snpMeasurement),
        reportDataHash: Array.from(v1ReportDataHash),
        modelWeightsHash: Array.from(modelHash),
        runtimeVersion: "bitnet.cpp@p0-scaffold-v1",
        attestationGrade: { noTee: {} },
        bindingVersion: 1,
        registryHash: Array.from(zeroRegistryHash),
      })
      .accounts({ payer: provider.wallet.publicKey })
      .rpc({ commitment: "confirmed" });

    const att = await program.account.attestationAccount.fetch(v1Pda);
    expect(att.bindingVersion).to.equal(1);
    expect(Buffer.from(att.registryHash)).to.deep.equal(zeroRegistryHash);
    expect(Buffer.from(att.modelWeightsHash)).to.deep.equal(modelHash);
    expect(Buffer.from(att.reportDataHash)).to.deep.equal(v1ReportDataHash);
  });

  it("rejects an unknown binding version", async () => {
    const badEnclave = nacl.sign.keyPair();
    try {
      await program.methods
        .registerAttestation({
          enclaveEd25519Pubkey: Array.from(badEnclave.publicKey),
          snpMeasurement: Array.from(snpMeasurement),
          reportDataHash: Array.from(reportDataHash),
          modelWeightsHash: Array.from(modelHash),
          runtimeVersion: "bitnet.cpp@p0-scaffold",
          attestationGrade: { noTee: {} },
          bindingVersion: 3,
          registryHash: Array.from(registryHash),
        })
        .accounts({ payer: provider.wallet.publicKey })
        .rpc({ commitment: "confirmed" });
      assert.fail("should have failed: unknown binding version");
    } catch (err: any) {
      assert.match(err.toString(), /InvalidBindingVersion/);
    }
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
          bindingVersion: 2,
          registryHash: Array.from(registryHash),
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
      assert.match(
        err.toString(),
        /precompile|signature|SendTransactionError/i
      );
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
  // CU notes
  // ---------------------------------------------------------------------------

  after(() => {
    if (cuLog.length === 0) return;
    console.log("\n  Compute units consumed (localnet):");
    for (const { label, cu, txBytes } of cuLog) {
      console.log(
        `    ${label.padEnd(42)} ${String(cu).padStart(
          7
        )} CU  (tx msg ${txBytes} B)`
      );
    }
  });
});
