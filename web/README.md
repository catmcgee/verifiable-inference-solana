# web — measurement console

Next.js (App Router, TypeScript) chat UI for the verified-inference server,
with a live measurement panel: TTFT, throughput, ITL p50, e2e, SEV state,
attestation grade, receipt, and a running cost estimate from registry prices.

## Run

```sh
# 1. start the server (repo root; mock backend works locally)
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

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_VINFER_URL` | `http://127.0.0.1:8477` | verified-inference server base URL |

The browser talks same-origin to `/vinfer/*`; `next.config.ts` rewrites that
to `NEXT_PUBLIC_VINFER_URL`. This is deliberate: the FastAPI server serves no
CORS headers, and the proxy makes the UI work against it unmodified. Set the
variable before `npm run dev` / `npm run build` (rewrites are read from config
at startup):

```sh
NEXT_PUBLIC_VINFER_URL=http://sunburst-box:8477 npm run dev
```

## Endpoints used

- `GET /v1/models` — model picker (id, quant, runtime, legs, status, prices)
- `GET /v1/attestation` — grade, binding version, registry hash (refetchable)
- `POST /v1/chat/completions` — non-streaming; `x_vinfer.metrics` and
  `x_vinfer.receipt` feed the panel

The UI renders only what the API returns; absent fields display as `—`.
Receipt links go to the attestation registry program on Solana explorer
(devnet); a per-receipt `attestation_pda` field is used instead if the server
ever returns one.

## Structure

```
app/layout.tsx                  shell + metadata
app/page.tsx                    state: registry, selection, chat, session totals
app/globals.css                 design tokens + all styling
components/Pickers.tsx          leg selector (A/B/C; D disabled) + model chips
components/Chat.tsx             message ledger, generating sweep, composer
components/MeasurementPanel.tsx meters, execution/SEV, attestation, receipt, session
lib/api.ts                      typed client for the /v1 surface
lib/format.ts                   number/hash formatting ("—" for missing)
lib/labels.ts                   deadpan copy tables: sev_mode, grades, legs
```
