import {
  Activity,
  Box,
  CheckCircle2,
  Clock3,
  Cloud,
  Code2,
  Cpu,
  Database,
  Fingerprint,
  Globe2,
  LockKeyhole,
  MonitorDot,
  Network,
  Server,
  ShieldCheck,
  SquareTerminal,
  WalletCards,
} from "lucide-react";
import { Masthead } from "@/components/Masthead";

const verificationSteps = [
  ["1", "AMD certificate chain", "Versioned Chip Endorsement Key (VCEK) → AMD SEV Signing Key (ASK) → AMD Root Key (ARK)."],
  ["2", "Launch policy", "The signed measurement, build identity, and reported execution mode must match an exact approved tuple."],
  ["3", "Registry record", "The Solana PDA binds the enclave key to the model registry and binding version."],
  ["4", "Inference receipt", "The boot key signs prompt, response, and model hashes. Solana stores those hashes only; it never receives the prompt or response."],
] as const;

export default function HowItWorksPage() {
  return (
    <div className="frame">
      <Masthead active="how-it-works" />

      <main className="how-scroll">
        <div className="how-wrap">
          <section className="how-intro">
            <div className="eyebrow">Primary route</div>
            <h1>Open-source inference inside a TEE</h1>
            <p>
              A Trusted Execution Environment (TEE) isolates the model server
              inside a confidential virtual machine (CVM). This route uses
              AMD Secure Encrypted Virtualization with Secure Nested Paging
              (SEV-SNP). The browser verifies the guest, then encrypts the
              prompt to a boot-generated HPKE key signed by the guest&apos;s boot
              key. The live request path keeps chat text between the browser
              and the TEE. Measured direct boot and read-only dm-verity volumes
              bind the live guest to the approved code, runtimes, and weights.
            </p>
          </section>

          <section className="tee-primary" aria-label="Primary verified inference route">
            <div className="tee-route-diagram" aria-label="Verified inference request path">
              <div
                className="tee-stage"
                tabIndex={0}
                aria-describedby="client-stage-help"
                data-tooltip="The client rejects the enclave key unless the AMD certificate chain, launch policy, and registry binding all verify."
              >
                <span className="stage-kicker">1 · client</span>
                <MonitorDot />
                <b>Check the evidence</b>
                <p>The console displays it; sealed clients require it.</p>
                <span className="sr-only" id="client-stage-help">The client rejects the enclave key unless the AMD certificate chain, launch policy, and registry binding all verify.</span>
              </div>
              <div className="tee-arrow"><span>request</span>→</div>
              <div
                className="tee-stage"
                tabIndex={0}
                aria-describedby="edge-stage-help"
                data-tooltip="For the TEE route, the public edge forwards HPKE ciphertext and cannot decrypt the prompt or generated text. It can still see routing metadata such as the model and token limit."
              >
                <span className="stage-kicker">2 · public edge</span>
                <Network />
                <b>Forward ciphertext</b>
                <p>The edge sees routing metadata, not the chat text.</p>
                <span className="sr-only" id="edge-stage-help">For the TEE route, the public edge forwards HPKE ciphertext and cannot decrypt the prompt or generated text. It can still see routing metadata such as the model and token limit.</span>
              </div>
              <div className="tee-arrow"><span>forward</span>→</div>
              <div
                className="tee-stage model-stage"
                tabIndex={0}
                aria-describedby="tee-stage-help"
                data-tooltip="Both inference and receipt signing happen inside the same SEV-SNP guest. Measured boot and dm-verity independently fix its code and weight identity."
              >
                <span className="stage-kicker">3 · TEE boundary</span>
                <Box />
                <b>Run and sign inside SEV-SNP</b>
                <div className="tee-inner-grid">
                  <div>
                    <Cpu />
                    <strong>Open model</strong>
                    <span>llama.cpp or bitnet.cpp</span>
                  </div>
                  <div>
                    <Fingerprint />
                    <strong>Boot key</strong>
                    <span>signs hash-only receipt</span>
                  </div>
                </div>
                <span className="sr-only" id="tee-stage-help">Both inference and receipt signing happen inside the same SEV-SNP guest. Measured boot and dm-verity independently fix its code and weight identity.</span>
              </div>
              <div className="tee-arrow"><span>encrypted</span>→</div>
              <div
                className="tee-stage"
                tabIndex={0}
                aria-describedby="response-stage-help"
                data-tooltip="The generated text is encrypted inside the TEE. The public edge forwards ciphertext, and only the browser opens it with the session key."
              >
                <span className="stage-kicker">4 · client response</span>
                <Activity />
                <b>Decrypt the response</b>
                <p>The browser opens the generated text locally.</p>
                <span className="sr-only" id="response-stage-help">The generated text is encrypted inside the TEE. The public edge forwards ciphertext, and only the browser opens it with the session key.</span>
              </div>
              <div className="tee-arrow"><span>receipt</span>→</div>
              <div
                className="tee-stage"
                tabIndex={0}
                aria-describedby="chain-stage-help"
                data-tooltip="The Solana program stores fixed-length hashes, the enclave public key, timestamp, and signature metadata. It never receives prompt text, response text, or user identity."
              >
                <span className="stage-kicker">5 · public record</span>
                <Database />
                <b>Anchor the receipt</b>
                <p>Solana devnet stores hashes and signature metadata only.</p>
                <span className="sr-only" id="chain-stage-help">The Solana program stores fixed-length hashes, the enclave public key, timestamp, and signature metadata. It never receives prompt text, response text, or user identity.</span>
              </div>
              <div className="tee-note">
                <CheckCircle2 />
                <div>
                  <b>What the attestation means</b>
                  <span>SEV-SNP signs the confidential virtual machine launch. The browser requires that evidence to match local policy before it sends ciphertext.</span>
                </div>
              </div>
            </div>
          </section>

          <section className="how-section state-section">
            <div className="eyebrow">Execution identity</div>
            <h2>What the current deployment proves</h2>
            <div className="state-grid">
              <article className="state-item live">
                <div className="state-title"><Activity size={18} /><b>Live now</b></div>
                <h3>Proves a real TEE started</h3>
                <p>
                  The browser verifies the signed launch report, policy, boot
                  key, and receipt. The public guest can still be changed after
                  it starts, so this does not yet prove the exact server code
                  and model files stayed unchanged.
                </p>
                <span>Current scope: real TEE, files not fixed</span>
              </article>
              <article className="state-item target">
                <div className="state-title"><Code2 size={18} /><b>Next step</b></div>
                <h3>Prove the exact code and model</h3>
                <p>
                  The hardened version makes the server and model files
                  read-only, checks their hashes before starting, and binds
                  that identity into the attestation. It works in an isolated
                  BitNet test guest but is not public yet. This strengthens the
                  TEE route; it is not a zero-knowledge proof.
                </p>
                <span>Status: tested with BitNet, public cutover pending</span>
              </article>
            </div>
          </section>

          <section className="how-section verify-focus">
            <div className="eyebrow">Prompt privacy</div>
            <h2>The TEE route is sealed in both directions</h2>
            <div className="limits-grid">
              <div>
                <h3>What stays private</h3>
                <p>
                  The browser verifies the attested HPKE key before encrypting.
                  The prompt is decrypted only inside the TEE. The generated
                  text is encrypted inside the TEE and decrypted only in the
                  browser. This describes the sealed browser endpoint running
                  the approved server.
                </p>
              </div>
              <div>
                <h3>What remains visible</h3>
                <p>
                  The public edge sees the selected model, token limit,
                  ciphertext size, timing, and authenticated session. Solana
                  sees the enclave key, timestamp, and prompt, response, and
                  model hashes. Hashes do not contain the original text.
                </p>
              </div>
            </div>
            <p className="tee-definition">
              Prompt text, response text, user identifiers, and encryption keys
              are never written to Solana. The baseline and Claude comparison
              routes use TLS but do not provide this end-to-end privacy boundary.
              The OpenAI-compatible endpoint also accepts plaintext messages
              under TLS for client compatibility.
            </p>
          </section>

          <section className="how-section verify-focus">
            <div className="eyebrow">Browser verification</div>
            <h2>The evidence chain</h2>
            <div className="verification-grid">
              {verificationSteps.map(([index, title, text]) => (
                <article key={title}>
                  <span>{index}</span>
                  <b>{title}</b>
                  <p>{text}</p>
                </article>
              ))}
            </div>
            <div className="limits-grid">
              <div>
                <h3>What it establishes</h3>
                <p>A specific AMD-protected guest produced a receipt for exact input, output, and model hashes.</p>
                <p>The live public route fixes code and weight identity with measured boot and read-only dm-verity volumes.</p>
              </div>
              <div>
                <h3>What it does not establish</h3>
                <p>It does not prove that the model&apos;s answer is correct.</p>
                <p>It does not remove trust in AMD hardware, the approved policy, or the operator that chose that policy.</p>
                <p>It does not protect against a modified web client that reads text before encryption; the loaded client bundle remains part of the trust base.</p>
              </div>
            </div>
          </section>

          <section className="how-section solana-section">
            <div className="eyebrow">Solana state</div>
            <h2>One app program, two PDA account types</h2>
            <p className="solana-lede">
              Solana does not run the model or receive chat text. It keeps a
              public link from one TEE boot key to its attestation record and
              numbered, hash-only inference receipts.
            </p>

            <div
              className="solana-map"
              aria-label="How the Solana programs, accounts, and PDAs work together"
            >
              <div className="solana-actors">
                <article>
                  <span>off-chain source</span>
                  <Fingerprint />
                  <div>
                    <h3>TEE boot key</h3>
                    <p>Signs each inference&apos;s prompt, response, and model hashes.</p>
                  </div>
                </article>
                <article>
                  <span>Solana account</span>
                  <WalletCards />
                  <div>
                    <h3>Relay payer wallet</h3>
                    <p>Submits transactions and pays their fees and account rent.</p>
                  </div>
                </article>
              </div>

              <div className="solana-submit" aria-hidden="true">
                <span>submits a transaction</span>
                <b>↓</b>
              </div>

              <div className="solana-ledger">
                <div className="solana-helpers">
                  <span className="solana-column-label">Solana helpers</span>
                  <article>
                    <ShieldCheck />
                    <div><b>Ed25519 program</b><span>verifies the enclave signature</span></div>
                  </article>
                  <article>
                    <SquareTerminal />
                    <div><b>Instructions sysvar</b><span>proves that verification came first</span></div>
                  </article>
                  <article>
                    <Database />
                    <div><b>System program</b><span>creates both payer-funded PDA types</span></div>
                  </article>
                  <article>
                    <Clock3 />
                    <div><b>Clock sysvar</b><span>supplies each recorded slot</span></div>
                  </article>
                </div>

                <div className="solana-map-arrow" aria-hidden="true">→</div>

                <article className="solana-program">
                  <span>app program</span>
                  <Box />
                  <h3>Verified Inference</h3>
                  <code>Dp5L…vXEkx</code>
                  <div>
                    <b>register_attestation</b>
                    <p>Records a previously verified boot identity.</p>
                  </div>
                  <div>
                    <b>post_receipt</b>
                    <p>Requires the signature check and a registered boot key.</p>
                  </div>
                </article>

                <div className="solana-map-arrow" aria-hidden="true">→</div>

                <div className="solana-accounts">
                  <span className="solana-column-label">Program-owned PDAs</span>
                  <article className="attestation-account">
                    <span>one per TEE boot</span>
                    <h3>Attestation PDA</h3>
                    <code>[&quot;attestation&quot;, boot_key]</code>
                    <p>Boot key, SNP measurement and grade, runtime, registry binding, slot, and next receipt index.</p>
                  </article>
                  <article className="receipt-account">
                    <span>one per inference</span>
                    <h3>Receipt PDA</h3>
                    <code>[&quot;receipt&quot;, boot_key, index]</code>
                    <p>Prompt, response, and model hashes; timestamp, slot, and index. No chat text or user identity.</p>
                  </article>
                </div>
              </div>

              <div className="solana-transactions">
                <div><b>01 · boot registration</b><span>Verify the AMD evidence off-chain, then create the Attestation PDA.</span></div>
                <div><b>02 · every inference</b><span>Verify the signature and post the next Receipt PDA in the same atomic transaction; then increment the attestation counter.</span></div>
              </div>
              <p className="solana-footnote">
                No token program is involved. The payer can post and fund the
                records, but it cannot forge the TEE boot key&apos;s signature.
              </p>
            </div>
          </section>

          <section className="how-section deployment-focus">
            <div className="eyebrow">Deployment</div>
            <h2>How a public request reaches the TEE</h2>
            <p className="deployment-lede">
              The application runs on the Sunburst bare-metal server. Caddy is
              the only public web entry point; it handles HTTPS and forwards
              requests over a private host connection to the confidential
              virtual machine.
            </p>

            <div className="deploy-route" aria-label="Deployed request path">
              <article
                className="deploy-stage"
                tabIndex={0}
                data-tooltip="The browser loads the console over HTTPS. For TEE inference it verifies the attestation, then seals the chat before sending it."
              >
                <span>1 · internet</span>
                <Globe2 />
                <b>Browser</b>
                <p>Loads the console and starts an HTTPS request.</p>
              </article>
              <div className="deploy-connector" aria-hidden="true">→</div>
              <article
                className="deploy-stage"
                tabIndex={0}
                data-tooltip="Caddy serves the static console, obtains and renews its HTTPS certificate, redirects HTTP to HTTPS, and routes API traffic. It is not an inference or attestation component."
              >
                <span>2 · public edge</span>
                <Network />
                <b>Caddy</b>
                <p>Terminates HTTPS and routes the request.</p>
              </article>
              <div className="deploy-connector" aria-hidden="true">→</div>
              <article
                className="deploy-stage"
                tabIndex={0}
                data-tooltip="127.0.0.1 is the server's loopback address. The forwarded API port can be reached from the Sunburst host but cannot be opened directly from the internet."
              >
                <span>3 · private hop</span>
                <Server />
                <b>Loopback port</b>
                <p><code>127.0.0.1</code> forwards into the virtual machine.</p>
              </article>
              <div className="deploy-connector" aria-hidden="true">→</div>
              <article
                className="deploy-stage tee-deploy-stage"
                tabIndex={0}
                data-tooltip="FastAPI and the selected llama.cpp or bitnet.cpp runtime execute inside the SEV-SNP guest. Only this guest can open the browser's sealed TEE request."
              >
                <span>4 · confidential guest</span>
                <Box />
                <b>SNP virtual machine</b>
                <p>Decrypts, runs the model, and encrypts the response.</p>
              </article>
            </div>

            <div className="deployment-details">
              <article>
                <div className="deployment-detail-icon privacy"><LockKeyhole /></div>
                <div>
                  <h3>Where privacy comes from</h3>
                  <p>
                    TLS protects the browser-to-Caddy connection. HPKE adds a
                    second layer from the browser all the way into the verified
                    TEE, so normal Caddy and host forwarding handles ciphertext,
                    not chat text. The current guest administrator remains
                    trusted because its userspace is mutable; the measured,
                    read-only guest is the production target. The private port
                    limits network access but does not provide content privacy.
                  </p>
                </div>
              </article>
              <article>
                <div className="deployment-detail-icon operator"><SquareTerminal /></div>
                <div>
                  <h3>Where Secure Shell (SSH) is used</h3>
                  <p>
                    SSH is an operator-only maintenance path used to deploy
                    builds, start services, and inspect the server. A browser
                    request never uses SSH, and the application never receives
                    or sends the operator&apos;s SSH key.
                  </p>
                </div>
              </article>
              <article>
                <div className="deployment-detail-icon receipt"><Database /></div>
                <div>
                  <h3>How Solana fits in</h3>
                  <p>
                    The TEE signs prompt, response, and model hashes. A relay on
                    the host posts that fixed-size receipt to Solana devnet.
                    Prompt text, response text, chat history, and user identity
                    are never included in the on-chain instruction or account.
                  </p>
                </div>
              </article>
            </div>

            <div className="deploy-notes">
              <div><b>Test access</b><span>Authenticated browser sessions reach the API without payment.</span></div>
              <div><b>pay.sh</b><span>An x402 gateway can sit in front of the OpenAI-compatible TLS endpoint. That endpoint is not end-to-end sealed, and the listing is not published.</span></div>
            </div>
          </section>

          <section className="how-section comparison-section">
            <div className="eyebrow">Comparison routes</div>
            <h2>Why the other paths exist</h2>
            <div className="comparison-grid">
              <article>
                <div className="compare-icon green"><Server /></div>
                <div>
                  <h3>Open-source models without TEE</h3>
                  <p>The same host and model runtimes provide the baseline. Comparing this with the protected route isolates the TEE latency, throughput, and cost.</p>
                  <span>No hardware-backed execution identity.</span>
                </div>
              </article>
              <article>
                <div className="compare-icon orange"><Cloud /></div>
                <div>
                  <h3>Claude through the TEE proxy</h3>
                  <p>This measures the overhead of an attested proxy. Anthropic receives the plaintext prompt and its model inference is not verified.</p>
                  <span>Only the proxy behavior is attested.</span>
                </div>
              </article>
            </div>
          </section>

        </div>
      </main>
    </div>
  );
}
