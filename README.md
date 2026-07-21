# verified-inference

Measures when open-source inference inside a Trusted Execution Environment
(TEE) is worth its latency and cost. The system compares the same local models
with and without a TEE, measures a Claude proxy separately, anchors evidence on
Solana devnet, and exposes the results through an API, CLI, report, and browser.

- Console: `https://verified-inference.vercel.app`
- API: `https://vinfer.usefrogpay.com`

## How it works

1. The browser verifies the AMD certificate chain, signed Secure Encrypted
   Virtualization with Secure Nested Paging (SEV-SNP) report, local policy,
   boot key, and Solana attestation record.
2. Hybrid Public Key Encryption (HPKE) seals browser chat to a key created
   inside the verified guest. The guest encrypts generated text back to the
   browser.
3. Caddy handles public HTTPS and forwards the request through a loopback-only
   host port into the confidential virtual machine. On the sealed browser path,
   Caddy and the normal host forwarding path see routing metadata and
   ciphertext, not chat text.
4. FastAPI and the selected `llama.cpp` or `bitnet.cpp` runtime execute inside
   a read-only dm-verity guest. The public guest has no SSH service or QEMU
   monitor; deployment work happens in a separate, non-public builder VM.
5. The guest signs fixed-size prompt, response, and model hashes. A host relay
   posts those hashes and signature metadata to Solana devnet. Prompt text,
   response text, chat history, and user identity are never posted on-chain.

The loaded browser code remains part of the trust boundary. Receipt hashes do
not expose text directly, but low-entropy text can still be tested by guessing
and hashing candidate values.

## Available routes

- **Open-source models inside the TEE:** end-to-end sealed browser chat,
  independently checked measured-boot attestation, immutable code and model
  volumes, and confirmed devnet receipts.
- **Open-source models without the TEE:** the same-box performance baseline.
  Transport Layer Security (TLS) protects transport, but the host sees text.
- **Claude proxy:** measures attested-proxy overhead. Anthropic sees plaintext,
  and Claude inference is not verified.
All five registry models are live inside the 832 GiB SNP guest: BitNet, 8B Q4,
8B Q8, 70B Q4, and GLM-5.2 Q4. The browser exposes 1,254 unique request records
plus session measurements.

## Current trust boundary

The public guest boots a directly measured kernel and initrd, then mounts its
root filesystem and both model volumes read-only through dm-verity. Browser
verification permits one exact `(measurement, build, execution mode)` tuple;
old mutable builds are not trusted. This proves the approved image booted with
the declared model bytes. It does not prove model correctness, eliminate CPU
side channels, or prevent the operator or hosting provider from taking the
service offline.

The published dataset reports only the configurations that were actually
measured. It does not extrapolate unmeasured model, context, thread, or
encryption combinations.

BitNet remains available because it is the 1.58-bit measurement anchor, but its
published `i2_s` runtime produces unreliable chat answers in live checks. The
browser therefore defaults to the more capable 8B Q4 model.

## Interfaces

`models.yaml` is the single model registry. The canonical inference surface is
OpenAI-compatible `POST /v1/chat/completions`; the browser uses
`POST /v1/chat_e2e` for bidirectional sealing. Free endpoints expose models,
attestation, and receipts.

The OpenAI-compatible endpoint accepts normal plaintext OpenAI messages under
TLS; it does not inherit the browser endpoint's end-to-end sealing. The current
x402 gateway targets that compatibility endpoint, so an edge payment gateway
can read those messages. Clients that require the TEE privacy boundary must use
the sealed endpoint or its CLI wrapper.

Browser testing uses an authenticated session without payment. The generated
pay/x402 gateway sits in front of the same OpenAI-compatible API; its sandbox
flow passes, but no mainnet gateway or provider listing is published.

## Run and verify

```bash
export VINFER_URL=https://vinfer.usefrogpay.com
export VINFER_AUTH_TOKEN="strong-gateway-bearer-token"
export VINFER_ACCESS_CODE="operator-issued-browser-code"

uv run vinfer attest
uv run vinfer infer --model bitnet-2b --prompt 'hello' --e2e
uv run vinfer verify runs/snp-receipt.json
make test
make check
make verify-registry
make report
make pay-sandbox-test
```

Add a model by placing and hashing its weights, adding one `models.yaml` entry,
then running `make bench MODEL=<id>`, `make pricing`, restarting and
re-attesting the origin, and running `make payskill`.

## Project rules

- Reference the Sunburst SSH key by path only; never read, print, or commit it.
- Keep model configuration in `models.yaml`; pricing and pay artifacts are
  generated from it.
- Keep prompt/response plaintext and user identifiers out of logs and Solana.
- Never upgrade an attestation grade or verification result without evidence.
- Never publish the pay provider listing from a generation script.

Detailed host evidence is in [recon/findings.md](recon/findings.md). The
measured-boot procedure and test-maintained Solana compute data remain beside
their implementations.
