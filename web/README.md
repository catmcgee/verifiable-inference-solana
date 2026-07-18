# web — measurement console

Next.js (App Router, TypeScript) chat UI for the verified-inference server,
with a live measurement panel: TTFT, throughput, ITL p50, e2e, SEV state,
attestation grade, receipt, and a running cost estimate from registry prices.

## Run

```sh
# 1. start the server and real model runtimes (repo root)
uvicorn server.main:app --port 8477

# 2. start the UI
cd web
npm install
npm run dev          # http://localhost:3000
```

Production build:

```sh
npm run build
npm start
```

Public console: `https://console.213.239.141.40.sslip.io`. It is built as a
static export and served by the API host's Caddy instance; same-origin
`/vinfer/*` requests proxy to the standing SNP guest. Enter the operator-issued
test access code once; the API exchanges it for a short-lived Secure, HttpOnly,
SameSite=Strict cookie. The code is not embedded in the bundle or stored in
browser storage. Measurements and attestation remain freely readable.
Both `/measurements` and `/measurements/` resolve. The generated dataset includes
every unique, schema-valid request from `runs/*.jsonl`, plus session rows,
aggregate charts, warmup markers, filters, and pagination.

For the TEE route, the browser independently verifies the SNP report, AMD
certificate chain, local policy, signed HPKE key, and devnet attestation PDA
before enabling Run. Chat history is HPKE-sealed in the browser. Streamed token
chunks, the complete response, metrics, and usage are encrypted back under the
exported session key. Baseline and Claude comparison routes use normal TLS and
are labeled with their weaker privacy properties.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_VINFER_URL` | `http://127.0.0.1:8477` | verified-inference server base URL |

The production origin also requires `VINFER_REQUIRE_AUTH=1` and an owner-only
`VINFER_AUTH_TOKEN`. The external pay gateway receives that value as
`VINFER_ORIGIN_TOKEN` and injects it only after x402 verification.

The browser talks same-origin to `/vinfer/*`; `next.config.ts` rewrites that
to `NEXT_PUBLIC_VINFER_URL`. This is deliberate: the FastAPI server serves no
CORS headers, and the proxy makes the UI work against it unmodified. Set the
variable before `npm run dev` / `npm run build` (rewrites are read from config
at startup):

```sh
NEXT_PUBLIC_VINFER_URL=http://sunburst-box:8477 npm run dev
```

For the Caddy-hosted export:

```sh
VINFER_STATIC_EXPORT=1 \
NEXT_PUBLIC_VINFER_URL=https://verified-inference.213.239.141.40.sslip.io \
npm run build
```

## Endpoints used

- `GET /v1/models` — model picker (id, quant, runtime, legs, status, prices)
- `GET /v1/attestation` — grade, binding version, registry hash (refetchable)
- `GET|POST|DELETE /v1/auth/session` — status, sign-in, and sign-out for browser testing
- `POST /v1/chat_e2e` — attestation-gated encrypted SSE for the TEE route
- `POST /v1/chat/completions` — TLS-protected SSE for baseline and Claude comparisons

The UI recomputes the versioned request and response hashes, verifies the
receipt signature, and reads the exact attestation and receipt PDAs directly
from Solana devnet. Receipt links point to those records. Absent fields display
as `—`; an unposted receipt is never described as confirmed.

## Structure

```
app/layout.tsx                  shell + metadata
app/page.tsx                    state: registry, selection, chat, session totals
app/measurements/page.tsx       measured results, filters, and raw run evidence
app/how-it-works/page.tsx       deployment, privacy, and verification explanation
app/globals.css                 design tokens + all styling
components/Masthead.tsx         shared site navigation
components/Pickers.tsx          live-leg indicator + available-model chips
components/Chat.tsx             message ledger, generating sweep, composer
components/MeasurementPanel.tsx meters, execution/SEV, attestation, receipt, session
lib/api.ts                      typed client for the /v1 surface
lib/e2e.ts                      browser HPKE session and response decryption
lib/attestationVerifier.ts      AMD/policy/PDA/receipt verification in browser
lib/format.ts                   number/hash formatting ("—" for missing)
lib/labels.ts                   deadpan copy tables: sev_mode, grades, legs
```
