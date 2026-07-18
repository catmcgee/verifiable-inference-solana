import {
  Activity,
  Box,
  CheckCircle2,
  Cloud,
  Code2,
  Cpu,
  Database,
  Fingerprint,
  Gauge,
  KeyRound,
  MonitorDot,
  Network,
  ReceiptText,
  Server,
} from "lucide-react";
import { Masthead } from "@/components/Masthead";

const requestSteps = [
  [MonitorDot, "Check the evidence", "The browser verifies the AMD certificate chain, launch policy, registry record, and boot key before it sends a prompt."],
  [KeyRound, "Encrypt the prompt", "Hybrid Public Key Encryption (HPKE) seals the chat to the verified key created inside the guest at boot. Transport Layer Security (TLS) protects the outer connection too."],
  [Cpu, "Run the open model", "llama.cpp or bitnet.cpp loads the selected public weights and streams tokens inside the confidential virtual machine."],
  [Fingerprint, "Hash and sign", "The server hashes the prompt, response, and model declaration, then signs only those hashes with its boot key."],
  [Database, "Post the receipt", "A host relay checks the signature and posts the hash-only receipt to Solana devnet."],
  [CheckCircle2, "Check the result", "The browser checks the receipt signature and its exact on-chain program-derived address (PDA) record."],
] as const;

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
              prompt to its boot key. Only the browser and the TEE decrypt the
              prompt and generated text.
            </p>
          </section>

          <section className="tee-primary" aria-label="Primary verified inference route">
            <div className="tee-route-diagram" aria-label="Verified inference request path">
              <div
                className="tee-stage client-stage"
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
                className="tee-stage edge-stage"
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
                className="tee-stage tee-stage-boundary"
                tabIndex={0}
                aria-describedby="tee-stage-help"
                data-tooltip="Both inference and receipt signing happen inside the same SEV-SNP guest. Measured boot is required before code and weight identity can be independently fixed."
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
                <span className="sr-only" id="tee-stage-help">Both inference and receipt signing happen inside the same SEV-SNP guest. Measured boot is required before code and weight identity can be independently fixed.</span>
              </div>
              <div className="tee-arrow"><span>hashes</span>→</div>
              <div
                className="tee-stage chain-stage"
                tabIndex={0}
                aria-describedby="chain-stage-help"
                data-tooltip="The Solana program stores fixed-length hashes, the enclave public key, timestamp, and signature metadata. It never receives prompt text, response text, or user identity."
              >
                <span className="stage-kicker">4 · public record</span>
                <Database />
                <b>Anchor the receipt</b>
                <p>Solana devnet stores hashes and signature metadata only.</p>
                <span className="sr-only" id="chain-stage-help">The Solana program stores fixed-length hashes, the enclave public key, timestamp, and signature metadata. It never receives prompt text, response text, or user identity.</span>
              </div>
              <div className="tee-return">
                <Activity />
                <div>
                  <b>Response returns to the client</b>
                  <span>The TEE encrypts the generated text; the browser decrypts it locally.</span>
                </div>
                <ReceiptText />
              </div>
            </div>
            <p className="tee-definition">
              SEV-SNP signs a report describing the confidential virtual
              machine launch. The console evaluates and displays that evidence;
              the TEE console requires it to pass before sending ciphertext.
            </p>
          </section>

          <section className="how-section state-section">
            <div className="eyebrow">Execution identity</div>
            <h2>What the current deployment proves</h2>
            <div className="state-grid">
              <article className="state-item live">
                <div className="state-title"><Activity size={18} /><b>Live now</b></div>
                <h3>Hardware-attested virtual machine</h3>
                <p>
                  The browser verifies the AMD-signed launch report, local
                  policy, registry record, boot-key signature, and receipt.
                  The current 832 gibibyte (GiB) guest still has mutable userspace, so the
                  operator can change code or weights after launch.
                </p>
                <span>Execution scope: guest-declared</span>
              </article>
              <article className="state-item target">
                <div className="state-title"><Code2 size={18} /><b>Hardened target</b></div>
                <h3>Measured code and model images</h3>
                <p>
                  Direct measured boot and device-mapper verity (dm-verity)
                  make the root filesystem and model images read-only and
                  hash-checked before the server starts. This pipeline is in
                  isolated testing and has not replaced the public guest yet.
                </p>
                <span>Execution scope: pending public cutover</span>
              </article>
            </div>
          </section>

          <section className="how-section">
            <div className="eyebrow">One request</div>
            <h2>From prompt to independently checked receipt</h2>
            <ol className="request-flow">
              {requestSteps.map(([Icon, title, text], index) => (
                <li key={title}>
                  <div className="flow-index">{index + 1}</div>
                  <div className="flow-icon"><Icon size={18} /></div>
                  <div><b>{title}</b><p>{text}</p></div>
                </li>
              ))}
            </ol>
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
                  browser.
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
                <p>The console tells you whether code and weight identity is guest-declared or fixed by measured boot.</p>
              </div>
              <div>
                <h3>What it does not establish</h3>
                <p>It does not prove that the model&apos;s answer is correct.</p>
                <p>It does not remove trust in AMD hardware, the approved policy, or the operator that chose that policy.</p>
                <p>It does not protect against a modified web client that reads text before encryption; the loaded client bundle remains part of the trust base.</p>
              </div>
            </div>
          </section>

          <section className="how-section deployment-focus">
            <div className="eyebrow">Deployment</div>
            <h2>Where each piece runs</h2>
            <div className="deploy-notes">
              <div><b>Sunburst</b><span>The bare-metal AMD host, confidential virtual machines, local model runtimes, and receipt relay.</span></div>
              <div><b>Public interface</b><span>OpenAI-compatible API: <code>POST /v1/chat/completions</code>.</span></div>
              <div><b>Test access</b><span>Authenticated browser sessions bypass payment. Registered boots post hash-only receipts to devnet.</span></div>
              <div><b>pay.sh</b><span>An x402 payment gateway can sit in front of the same API. The provider listing is not published yet.</span></div>
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

          <section className="zk-band">
            <div className="zk-mark"><Gauge size={24} /></div>
            <div>
              <div className="eyebrow">Zero-knowledge proof, pending hardware</div>
              <h2>Planned after Sunburst adds graphics processing units (GPUs)</h2>
              <p>
                Tachyon is the intended zero-knowledge (ZK) proving path for models
                up to 2.4B parameters. It is not live today: no GPU prover,
                proof timing, or ZK-verified
                inference result is claimed yet.
              </p>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
