/** Exercise the full vinfer-session-v1 escrow lifecycle on Solana devnet. */

import * as anchor from "@anchor-lang/core";
import { BN, Program } from "@anchor-lang/core";
import {
  Connection,
  Ed25519Program,
  Keypair,
  PublicKey,
  SYSVAR_INSTRUCTIONS_PUBKEY,
  Transaction,
} from "@solana/web3.js";
import {
  TOKEN_PROGRAM_ID,
  createMint,
  getAccount,
  getOrCreateAssociatedTokenAccount,
  mintTo,
} from "@solana/spl-token";
import { createHash, randomBytes } from "crypto";
import * as fs from "fs";
import * as path from "path";
import nacl from "tweetnacl";
import { fileURLToPath } from "url";

const DEVNET = "https://api.devnet.solana.com";
const CHANNEL_SEED = Buffer.from("channel");
const VAULT_SEED = Buffer.from("channel_vault");

function voucherMessage(
  channel: PublicKey,
  cumulative: BN,
  expiresAt: BN
): Buffer {
  return Buffer.concat([
    channel.toBuffer(),
    cumulative.toArrayLike(Buffer, "le", 8),
    expiresAt.toTwos(64).toArrayLike(Buffer, "le", 8),
  ]);
}

async function main(): Promise<void> {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const root = path.join(here, "..");
  const deployer = Keypair.fromSecretKey(
    Uint8Array.from(
      JSON.parse(
        fs.readFileSync(path.join(root, ".devnet-deployer.json"), "utf8")
      )
    )
  );
  const idl = JSON.parse(
    fs.readFileSync(
      path.join(root, "target", "idl", "verified_inference.json"),
      "utf8"
    )
  );
  const connection = new Connection(DEVNET, "confirmed");
  const provider = new anchor.AnchorProvider(
    connection,
    new anchor.Wallet(deployer),
    { commitment: "confirmed" }
  );
  anchor.setProvider(provider);
  const program = new Program(idl, provider);

  const payee = Keypair.generate();
  const voucherSigner = nacl.sign.keyPair();
  const channelId = randomBytes(32);
  const [channel] = PublicKey.findProgramAddressSync(
    [
      CHANNEL_SEED,
      deployer.publicKey.toBuffer(),
      payee.publicKey.toBuffer(),
      channelId,
    ],
    program.programId
  );
  const [vault] = PublicKey.findProgramAddressSync(
    [VAULT_SEED, channel.toBuffer()],
    program.programId
  );

  const mint = await createMint(
    connection,
    deployer,
    deployer.publicKey,
    null,
    6
  );
  const payerToken = await getOrCreateAssociatedTokenAccount(
    connection,
    deployer,
    mint,
    deployer.publicKey
  );
  const payeeToken = await getOrCreateAssociatedTokenAccount(
    connection,
    deployer,
    mint,
    payee.publicKey
  );
  await mintTo(
    connection,
    deployer,
    mint,
    payerToken.address,
    deployer,
    2_000_000
  );

  const signatures: Record<string, string> = {};
  signatures.open = await program.methods
    .openChannel({
      channelId: Array.from(channelId),
      authorizedSigner: Array.from(voucherSigner.publicKey),
      deposit: new BN(1_000_000),
      graceSeconds: 60,
    })
    .accountsPartial({
      payer: deployer.publicKey,
      payee: payee.publicKey,
      channel,
      mint,
      payerToken: payerToken.address,
      vault,
      tokenProgram: TOKEN_PROGRAM_ID,
    })
    .rpc();

  signatures.topUp = await program.methods
    .topUpChannel(new BN(500_000))
    .accountsPartial({
      payer: deployer.publicKey,
      channel,
      mint,
      payerToken: payerToken.address,
      vault,
      tokenProgram: TOKEN_PROGRAM_ID,
    })
    .rpc();

  const cumulativeAuthorized = new BN(900_000);
  const cumulativeSettlement = new BN(700_000);
  const expiresAt = new BN(Math.floor(Date.now() / 1000) + 600);
  const message = voucherMessage(channel, cumulativeAuthorized, expiresAt);
  const ed25519 = Ed25519Program.createInstructionWithPublicKey({
    publicKey: voucherSigner.publicKey,
    message,
    signature: nacl.sign.detached(message, voucherSigner.secretKey),
  });
  const settle = await program.methods
    .settleChannel(cumulativeAuthorized, cumulativeSettlement, expiresAt)
    .accountsPartial({
      channel,
      instructionsSysvar: SYSVAR_INSTRUCTIONS_PUBKEY,
    })
    .instruction();
  signatures.settle = await provider.sendAndConfirm(
    new Transaction().add(ed25519, settle)
  );

  signatures.requestClose = await program.methods
    .requestChannelClose()
    .accountsPartial({ payer: deployer.publicKey, channel })
    .rpc();

  signatures.finalize = await program.methods
    .finalizeChannel()
    .accountsPartial({
      caller: payee.publicKey,
      channel,
      payer: deployer.publicKey,
      payee: payee.publicKey,
      mint,
      vault,
      payerToken: payerToken.address,
      payeeToken: payeeToken.address,
      tokenProgram: TOKEN_PROGRAM_ID,
    })
    .signers([payee])
    .rpc();

  const payerFinal = await getAccount(connection, payerToken.address);
  const payeeFinal = await getAccount(connection, payeeToken.address);
  const channelClosed = (await connection.getAccountInfo(channel)) === null;
  const vaultClosed = (await connection.getAccountInfo(vault)) === null;
  if (
    payerFinal.amount !== 1_300_000n ||
    payeeFinal.amount !== 700_000n ||
    !channelClosed ||
    !vaultClosed
  ) {
    throw new Error(
      "final balances or account closure did not match the settlement"
    );
  }

  const result = {
    programId: program.programId.toBase58(),
    channel: channel.toBase58(),
    mint: mint.toBase58(),
    deposit: 1_500_000,
    settled: Number(payeeFinal.amount),
    refunded: Number(payerFinal.amount) - 500_000,
    channelClosed,
    vaultClosed,
    signatures,
    runHash: createHash("sha256")
      .update(Object.values(signatures).join("\n"))
      .digest("hex"),
  };
  const out = path.join(root, "..", "runs", "channel-devnet.json");
  fs.writeFileSync(out, JSON.stringify(result, null, 2) + "\n");
  console.log(JSON.stringify(result, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
