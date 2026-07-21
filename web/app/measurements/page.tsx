"use client";

// Measurements view: renders web/public/measurements.json verbatim.
// Every number on this page comes from that file; anything absent is "—".

import { Fragment, useEffect, useMemo, useState } from "react";
import { Masthead } from "@/components/Masthead";
import { DASH, fmtInt, fmtMs, trunc } from "@/lib/format";
import { explorerUrl, legLabel } from "@/lib/labels";

interface StreamAnchor {
  bare_metal_gbs?: number;
  plain_vm_gbs?: number;
  sev_es_gbs?: number;
  sev_es_tax_pct?: number;
  note?: string;
}

interface ThreadSweep {
  unit?: string;
  by_model_threads?: Record<string, Record<string, number>>;
  note?: string;
}

interface InferenceTax {
  by_model?: Record<
    string,
    { plain_vm_tok_s?: number; sev_es_tok_s?: number; tax_pct?: number }
  >;
  finding?: string;
}

interface RouteThroughput {
  unit?: string;
  shape?: {
    threads?: number;
    prompt_tokens?: number;
    output_tokens?: number;
    concurrency?: number;
    input_mode?: string;
  };
  open_models?: Record<
    string,
    {
      without_tee_tok_s?: number;
      snp_tee_tok_s?: number;
      tee_slowdown_pct?: number;
      samples_per_route?: number;
    }
  >;
  featured_glm?: {
    model?: string;
    without_tee_tok_s?: number;
    snp_tee_tok_s?: number;
    observed_slowdown_pct?: number;
    samples_per_route?: number;
    shape?: {
      threads?: number;
      requested_output_tokens?: number;
      concurrency?: number;
      input_mode?: string;
    };
    without_tee_environment?: string;
    snp_tee_environment?: string;
    snp_actual_output_tokens?: { min?: number; max?: number };
    note?: string;
  };
  claude_api?: {
    model?: string;
    direct_tok_s?: number;
    snp_proxy_tok_s?: number;
    proxy_slowdown_pct?: number;
    samples_per_route?: number;
    note?: string;
  };
  note?: string;
}

interface PricedModel {
  id: string;
  quant?: string;
  price_per_1m_in_usdc?: number;
  price_per_1m_out_usdc?: number;
}

interface RequestMeasurement {
  run_id: string;
  leg: string;
  model: string;
  sev_mode: string;
  input_mode: string;
  threads: number;
  prompt_tokens: number;
  output_tokens: number;
  concurrency: number;
  ttft_ms: number;
  tokens_per_s: number;
  e2e_ms: number;
  receipt_confirm_ms: number;
  solana_cu: number;
  ts: string;
  [key: string]: unknown;
}

interface SessionMeasurement {
  session_id: string;
  sev_mode: string;
  stream_triad_gbs: number;
  kernel: string;
  ts: string;
  [key: string]: unknown;
}

interface MeasurementsDoc {
  generated_from?: string;
  provenance?: Record<string, string>;
  stream_anchor?: StreamAnchor;
  thread_sweep?: ThreadSweep;
  inference_tax?: InferenceTax;
  route_throughput?: RouteThroughput;
  models?: PricedModel[];
  leg_c_api?: {
    model?: string;
    ttft_ms_median?: number;
    e2e_ms_median?: number;
    n?: number;
    proxied_ttft_ms_median?: number;
    proxied_e2e_ms_median?: number;
    proxied_n?: number;
    matched_shape_ttft_delta_ms?: number;
    raw_n?: number;
    note?: string;
  };
  snp_twin?: {
    by_model?: Record<
      string,
      {
        tax_pct_median?: number;
        tax_pct_min?: number;
        tax_pct_max?: number;
        matched_cells?: number;
      }
    >;
    note?: string;
  };
  hpke?: {
    delta_ms_median?: number;
    note?: string;
  };
  onchain_devnet?: {
    program_id?: string;
    register_attestation_cu?: number;
    post_receipt_cu?: number;
    devnet_measured_at?: string;
    note?: string;
  };
  request_measurements?: {
    rows?: RequestMeasurement[];
    warmup_run_ids?: string[];
    note?: string;
  };
  session_measurements?: {
    rows?: SessionMeasurement[];
    note?: string;
  };
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return `${v.toFixed(1)}%`;
}

function fmtGbs(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return v.toFixed(1);
}

function fmtTok(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return v.toFixed(1);
}

/** Registry prices carry 4 decimals; render them as stored. */
function fmtPrice4(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return DASH;
  return v.toFixed(4);
}

/* ---------- hero ---------- */

const THROUGHPUT_MODEL_ORDER = ["bitnet-2b", "8b-q4", "8b-q8", "70b-q4"];

function routeDifference(value: number | null | undefined): string {
  if (value == null) return DASH;
  if (Math.abs(value) < 1.5) return `≈ same (${Math.abs(value).toFixed(1)}% variation)`;
  return value > 0
    ? `${value.toFixed(1)}% slower in TEE`
    : `${Math.abs(value).toFixed(1)}% faster in TEE`;
}

function Hero({ doc }: { doc: MeasurementsDoc }) {
  const throughput = doc.route_throughput;
  const openRows = Object.entries(throughput?.open_models ?? {}).sort(
    ([left], [right]) => {
      const leftIndex = THROUGHPUT_MODEL_ORDER.indexOf(left);
      const rightIndex = THROUGHPUT_MODEL_ORDER.indexOf(right);
      return (leftIndex < 0 ? 99 : leftIndex) - (rightIndex < 0 ? 99 : rightIndex);
    },
  );
  const claude = throughput?.claude_api;
  const glm = throughput?.featured_glm;
  const shape = throughput?.shape;
  return (
    <section className="m-section m-hero">
      <div className="eyebrow">Primary measurement · generated tokens per second</div>
      <h1 className="m-metric-title">How fast each inference route generates text</h1>
      <p className="m-hero-intro">
        Tokens per second measures generation speed after the first token
        arrives. Higher is faster. Time to first token is measured separately
        below, so these numbers answer how quickly the response continues once
        it starts.
      </p>
      {glm && (
        <article className="glm-throughput-feature">
          <div className="glm-feature-copy">
            <span>Most important local model</span>
            <h2>GLM-5.2 Q4 route throughput</h2>
            <p>
              The same 436 GB model on the no-TEE route and inside the measured
              SNP guest.
            </p>
          </div>
          <div className="glm-route-value">
            <span>without TEE · bare metal</span>
            <strong>{fmtTok(glm.without_tee_tok_s)}</strong>
            <small>tokens / second</small>
          </div>
          <div className="glm-route-value tee">
            <span>inside measured SNP TEE</span>
            <strong>{fmtTok(glm.snp_tee_tok_s)}</strong>
            <small>tokens / second</small>
          </div>
          <div className="glm-route-gap">
            <strong>{fmtPct(glm.observed_slowdown_pct)}</strong>
            <span>lower on the observed SNP route</span>
          </div>
          <p className="glm-feature-note">
            {glm.samples_per_route ?? DASH} measured runs per route after warm-ups
            · {glm.shape?.threads ?? DASH} threads · {glm.shape?.requested_output_tokens ?? DASH}-token cap.
            The environments are not exact twins, so this is a production-route
            comparison—not an encryption-only tax.
          </p>
        </article>
      )}
      <div className="route-throughput-grid">
        <article className="route-throughput-panel open-routes">
          <div className="route-throughput-heading">
            <div>
              <h2>Open-source model routes</h2>
              <p>Same model and CPU: without TEE versus inside AMD SEV-SNP.</p>
            </div>
            <span className="route-sample">
              {shape?.threads ?? DASH} threads · {shape?.concurrency ?? DASH} request
            </span>
          </div>
          <div className="route-throughput-table" role="table" aria-label="Open-source model route throughput">
            <div className="route-throughput-row header" role="row">
              <span role="columnheader">model</span>
              <span role="columnheader">models without TEE</span>
              <span role="columnheader">models in TEE</span>
              <span role="columnheader">difference</span>
            </div>
            {openRows.map(([model, row]) => (
              <div className="route-throughput-row" role="row" key={model}>
                <span className="route-model" role="cell">{model}</span>
                <span className="route-tps" role="cell">
                  <strong>{fmtTok(row.without_tee_tok_s)}</strong>
                  <small><span className="route-mobile-label">without TEE · </span>tok/s</small>
                </span>
                <span className="route-tps tee" role="cell">
                  <strong>{fmtTok(row.snp_tee_tok_s)}</strong>
                  <small><span className="route-mobile-label">SNP TEE · </span>tok/s</small>
                </span>
                <span className="route-difference" role="cell">
                  {routeDifference(row.tee_slowdown_pct)}
                </span>
              </div>
            ))}
          </div>
        </article>

        <article className="route-throughput-panel claude-routes">
          <div className="route-throughput-heading">
            <div>
              <h2>Claude API routes</h2>
              <p>Claude Haiku, matched request shape.</p>
            </div>
          </div>
          <div className="claude-route-values">
            <div className="claude-route-value">
              <span>Claude direct API</span>
              <strong>{fmtTok(claude?.direct_tok_s)}</strong>
              <small>tokens / second</small>
            </div>
            <div className="claude-route-value tee">
              <span>Claude through TEE proxy</span>
              <strong>{fmtTok(claude?.snp_proxy_tok_s)}</strong>
              <small>tokens / second</small>
            </div>
          </div>
          <div className="route-verdict">
            {routeDifference(claude?.proxy_slowdown_pct)}
          </div>
          <p className="route-panel-note">
            Anthropic runs the model in both cases. The second route adds our
            attested TEE proxy; the observed difference is within normal API
            and network variation.
          </p>
        </article>
      </div>
      <p className="m-finding route-method">
        {throughput?.note} Test shape: 128-token prompt, 128 generated tokens,
        one concurrent request, with warm-ups excluded.
      </p>
    </section>
  );
}

/* ---------- stream anchor bars ---------- */

function AnchorBars({ a }: { a: StreamAnchor | undefined }) {
  const rows: { label: string; v?: number; tax?: number; hit?: boolean }[] = [
    { label: "bare metal reference", v: a?.bare_metal_gbs },
    { label: "plain VM · no SEV", v: a?.plain_vm_gbs },
    {
      label: "SEV-ES · encrypted",
      v: a?.sev_es_gbs,
      tax: a?.sev_es_tax_pct,
      hit: true,
    },
  ];
  const max = Math.max(...rows.map((r) => r.v ?? 0), 1);
  return (
    <section className="m-section">
      <div className="eyebrow">Diagnostic only · synthetic memory-bandwidth test</div>
      <div className="m-diagnostic-explainer">
        <strong>What the 26% means</strong>
        <span>
          STREAM continuously copies data through memory without running an AI
          model. In this historical SEV-ES test, encrypted RAM moved 26% less
          data per second. It is not paid when a TEE opens, it is not charged
          per request, and it does not mean inference is 26% slower.
        </span>
      </div>
      <div className="bars">
        {rows.map((r) => (
          <div className={`bar-row${r.hit ? " hit" : ""}`} key={r.label}>
            <div className="bar-label">{r.label}</div>
            <div className="bar-track">
              <div
                className="bar-fill"
                style={{ width: `${r.v != null ? (r.v / max) * 100 : 0}%` }}
              />
            </div>
            <div className="bar-val">
              {fmtGbs(r.v)} <span className="u">GB/s</span>
              {r.tax != null && (
                <span className="bar-tax">−{r.tax.toFixed(1)}%</span>
              )}
            </div>
          </div>
        ))}
      </div>
      <p className="m-chart-note">
        Kept as a low-level hardware diagnostic. Use the tokens-per-second
        route comparison at the top of this page to judge application speed.
      </p>
    </section>
  );
}

/* ---------- thread-saturation sweep ---------- */

const THREADS = [16, 32, 64, 128];

function SweepChart({ sweep }: { sweep: ThreadSweep | undefined }) {
  const byModel = sweep?.by_model_threads ?? {};
  const models = Object.keys(byModel);

  const all = models.flatMap((m) =>
    THREADS.map((t) => byModel[m]?.[String(t)]).filter(
      (v): v is number => v != null,
    ),
  );

  if (models.length === 0 || all.length === 0) {
    return (
      <section className="m-section">
        <div className="eyebrow">Throughput by central processing unit (CPU) threads</div>
        <div className="p-detail">no sweep rows in measurements.json.</div>
      </section>
    );
  }

  const W = 640;
  const H = 256;
  const M = { top: 24, right: 96, bottom: 30, left: 46 };
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;

  // log y-scale: the sweep spans ~8–160 tok/s; a linear axis flattens 70b-q4.
  const l0 = Math.log10(Math.min(...all));
  const l1 = Math.log10(Math.max(...all));
  const pad = (l1 - l0) * 0.09;
  const yLo = l0 - pad;
  const yHi = l1 + pad;

  const x = (i: number) => M.left + (i / (THREADS.length - 1)) * plotW;
  const y = (v: number) =>
    M.top + (1 - (Math.log10(v) - yLo) / (yHi - yLo)) * plotH;

  const gridVals = [10, 20, 50, 100].filter(
    (g) => Math.log10(g) > yLo && Math.log10(g) < yHi,
  );

  const unit = sweep?.unit === "tokens_per_s" ? "tok/s" : (sweep?.unit ?? "");

  return (
    <section className="m-section">
      <div className="eyebrow">
        Throughput by central processing unit (CPU) threads
      </div>
      <svg
        className="sweepchart"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Decode throughput (${unit}, log scale) against thread count for ${models.join(", ")}. Every model peaks at 32 to 64 threads and regresses at 128.`}
      >
        <text className="sw-tick" x={M.left} y={12}>
          {unit} (log)
        </text>
        {gridVals.map((g) => (
          <g key={g}>
            <line
              className="sw-grid"
              x1={M.left}
              x2={W - M.right}
              y1={y(g)}
              y2={y(g)}
            />
            <text className="sw-tick" x={M.left - 8} y={y(g) + 3} textAnchor="end">
              {g}
            </text>
          </g>
        ))}
        {THREADS.map((t, i) => (
          <text
            key={t}
            className="sw-tick"
            x={x(i)}
            y={H - 10}
            textAnchor="middle"
          >
            {t}
          </text>
        ))}
        <text className="sw-tick" x={x(THREADS.length - 1) + 26} y={H - 10}>
          threads
        </text>
        {models.map((m) => {
          const pts = THREADS.map((t, i) => {
            const v = byModel[m]?.[String(t)];
            return v != null ? { i, t, v } : null;
          }).filter((p): p is { i: number; t: number; v: number } => p != null);
          if (pts.length === 0) return null;
          const peak = pts.reduce((a, b) => (b.v > a.v ? b : a));
          const last = pts[pts.length - 1];
          // Drop the peak label below the point when another series sits
          // just above it at the same thread count.
          const crowdedAbove = models.some((m2) => {
            if (m2 === m) return false;
            const v2 = byModel[m2]?.[String(peak.t)];
            if (v2 == null) return false;
            const dy = y(peak.v) - y(v2);
            return dy > 0 && dy < 20;
          });
          const peakLabelY = crowdedAbove ? y(peak.v) + 16 : y(peak.v) - 8;
          return (
            <g key={m}>
              <polyline
                className="sw-line"
                points={pts.map((p) => `${x(p.i)},${y(p.v)}`).join(" ")}
              />
              {pts.map((p) => (
                <circle
                  key={p.t}
                  className="sw-hover"
                  cx={x(p.i)}
                  cy={y(p.v)}
                  r={9}
                >
                  <title>{`${m} · ${p.t} threads · ${fmtTok(p.v)} ${unit}`}</title>
                </circle>
              ))}
              <circle className="sw-dot" cx={x(peak.i)} cy={y(peak.v)} r={3} />
              <text
                className="sw-peak"
                x={x(peak.i)}
                y={peakLabelY}
                textAnchor="middle"
              >
                {fmtTok(peak.v)} @{peak.t}
              </text>
              <text className="sw-name" x={x(last.i) + 8} y={y(last.v) + 3}>
                {m}
              </text>
            </g>
          );
        })}
      </svg>
    </section>
  );
}

/* ---------- tables ---------- */

function TaxTable({ tax }: { tax: InferenceTax | undefined }) {
  const rows = Object.entries(tax?.by_model ?? {});
  return (
    <section className="m-section">
      <div className="eyebrow">Historical context · older SEV-ES model test</div>
      {rows.length === 0 ? (
        <div className="p-detail">no per-model rows.</div>
      ) : (
        <table className="m-table">
          <thead>
            <tr>
              <th>model</th>
              <th className="num">without TEE (tokens/s)</th>
              <th className="num">with SEV-ES (tokens/s)</th>
              <th className="num">difference</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([id, r]) => (
              <tr key={id}>
                <td className="dim">{id}</td>
                <td className="num v">{fmtTok(r.plain_vm_tok_s)}</td>
                <td className="num v">{fmtTok(r.sev_es_tok_s)}</td>
                <td className="num v">{fmtPct(r.tax_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="p-note">
        This older SEV-ES experiment produced the roughly 2% figure previously
        shown at the top. It is not the live SEV-SNP route. The primary table
        now uses the matched SNP data; negative values here are normal
        run-to-run measurement noise.
      </div>
    </section>
  );
}

function SnpTwinTable({ twin }: { twin: MeasurementsDoc["snp_twin"] }) {
  const rows = Object.entries(twin?.by_model ?? {});
  return (
    <section className="m-section">
      <div className="eyebrow">Matched baseline / AMD SEV with Secure Nested Paging (SEV-SNP)</div>
      {rows.length === 0 ? (
        <div className="p-detail">no matched twin rows.</div>
      ) : (
        <table className="m-table">
          <thead>
            <tr>
              <th>model</th>
              <th className="num">median slowdown</th>
              <th className="num">range</th>
              <th className="num">cells</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([id, row]) => (
              <tr key={id}>
                <td className="dim">{id}</td>
                <td className="num v">{fmtPct(row.tax_pct_median)}</td>
                <td className="num v">
                  {row.tax_pct_min == null || row.tax_pct_max == null
                    ? DASH
                    : `${fmtPct(row.tax_pct_min)} to ${fmtPct(row.tax_pct_max)}`}
                </td>
                <td className="num v">{fmtInt(row.matched_cells)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {twin?.note && <div className="p-note">{twin.note}</div>}
    </section>
  );
}

function PricingTable({ models }: { models: PricedModel[] | undefined }) {
  const rows = models ?? [];
  return (
    <section className="m-section">
      <div className="eyebrow">Estimated price per 1 million tokens</div>
      {rows.length === 0 ? (
        <div className="p-detail">no models listed.</div>
      ) : (
        <table className="m-table">
          <thead>
            <tr>
              <th>model</th>
              <th>quant</th>
              <th className="num">prompt tokens</th>
              <th className="num">generated tokens</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m) => (
              <tr key={m.id}>
                <td className="dim">{m.id}</td>
                <td className="dim">{m.quant ?? DASH}</td>
                <td className="num">{fmtPrice4(m.price_per_1m_in_usdc)}</td>
                <td className="num">{fmtPrice4(m.price_per_1m_out_usdc)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="p-note">
        Amounts are USDC per one million tokens. For example, 3.3407
        means 3.3407 USDC for one million prompt tokens.
      </div>
    </section>
  );
}

/* ---------- on-chain + misc ---------- */

function Onchain({ oc }: { oc: MeasurementsDoc["onchain_devnet"] }) {
  return (
    <section className="m-section">
      <div className="eyebrow">Receipt cost on Solana devnet</div>
      <dl className="kv wide">
        <dt>register attestation</dt>
        <dd>
          {oc?.register_attestation_cu != null ? (
            <>
              <span className="v">{fmtInt(oc.register_attestation_cu)}</span>{" "}
              compute units (CU)
            </>
          ) : (
            DASH
          )}
        </dd>
        <dt>single-instruction network</dt>
        <dd>devnet{oc?.devnet_measured_at ? ` · ${oc.devnet_measured_at}` : ""}</dd>
        <dt>post one receipt</dt>
        <dd>
          {oc?.post_receipt_cu != null ? (
            <>
              <span className="v">{fmtInt(oc.post_receipt_cu)}</span> CU
            </>
          ) : (
            DASH
          )}
        </dd>
        <dt>program</dt>
        <dd className="hash">
          {oc?.program_id ? (
            <a
              href={explorerUrl(oc.program_id)}
              target="_blank"
              rel="noreferrer"
            >
              {trunc(oc.program_id, 8)}
            </a>
          ) : (
            DASH
          )}
        </dd>
      </dl>
      {oc?.note && <div className="p-note">{oc.note}</div>}
    </section>
  );
}

function Misc({ doc }: { doc: MeasurementsDoc }) {
  const c = doc.leg_c_api;
  return (
    <section className="m-section">
      <div className="eyebrow">Encryption and Claude proxy</div>
      <dl className="kv wide">
        <dt>Hybrid Public Key Encryption (HPKE) overhead, median</dt>
        <dd>
          {doc.hpke?.delta_ms_median != null ? (
            <>
              <span className="v">{doc.hpke.delta_ms_median}</span> ms
            </>
          ) : (
            DASH
          )}
        </dd>
        <dt>Claude model</dt>
        <dd className={c?.model ? "" : "na"}>{c?.model ?? DASH}</dd>
        <dt>Claude direct time to first token (TTFT)</dt>
        <dd>
          {c?.ttft_ms_median != null ? (
            <span className="v">{fmtMs(c.ttft_ms_median)}</span>
          ) : (
            DASH
          )}
        </dd>
        <dt>Claude through proxy TTFT</dt>
        <dd>
          {c?.proxied_ttft_ms_median != null ? (
            <span className="v">{fmtMs(c.proxied_ttft_ms_median)}</span>
          ) : (
            DASH
          )}
        </dd>
        <dt>proxy TTFT overhead</dt>
        <dd>
          {c?.matched_shape_ttft_delta_ms != null ? (
            <span className="v">{fmtMs(c.matched_shape_ttft_delta_ms)}</span>
          ) : (
            DASH
          )}
        </dd>
        <dt>Claude direct end-to-end</dt>
        <dd>
          {c?.e2e_ms_median != null ? (
            <span className="v">{fmtMs(c.e2e_ms_median)}</span>
          ) : (
            DASH
          )}
        </dd>
        <dt>direct samples</dt>
        <dd className={c?.n != null ? "" : "na"}>{fmtInt(c?.n)}</dd>
      </dl>
      {c?.note && <div className="p-note">{c.note}</div>}
    </section>
  );
}

const PAGE_SIZE = 50;

function RawMeasurements({
  doc,
  initialLeg,
  initialRun,
  initialSession,
}: {
  doc: MeasurementsDoc;
  initialLeg: string;
  initialRun: string;
  initialSession: string;
}) {
  const rows = useMemo(
    () => doc.request_measurements?.rows ?? [],
    [doc.request_measurements?.rows],
  );
  const sessions = doc.session_measurements?.rows ?? [];
  const warmups = useMemo(
    () => new Set(doc.request_measurements?.warmup_run_ids ?? []),
    [doc.request_measurements?.warmup_run_ids],
  );
  const [leg, setLeg] = useState(initialLeg);
  const [model, setModel] = useState("all");
  const [run, setRun] = useState(initialRun);
  const [session, setSession] = useState(initialSession);
  const [page, setPage] = useState(0);
  const [openRequest, setOpenRequest] = useState<string | null>(null);
  const [openSession, setOpenSession] = useState<string | null>(null);
  const legs = useMemo(
    () => ["A", "B", "C", "C-direct", "C-proxied", "D"],
    [],
  );
  const models = useMemo(
    () => [...new Set(rows.map((row) => row.model))].sort(),
    [rows],
  );
  const filtered = rows.filter(
    (row) => (
      leg === "all" || row.leg === leg || (leg === "C" && row.leg.startsWith("C-"))
    ) && (model === "all" || row.model === model)
      && (!run || row.run_id.toLowerCase().includes(run.toLowerCase())),
  );
  const filteredSessions = sessions.filter(
    (row) => !session || row.session_id.toLowerCase().includes(session.toLowerCase()),
  );
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pages - 1);
  const visible = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);

  useEffect(() => setPage(0), [leg, model, run]);
  useEffect(() => setLeg(initialLeg), [initialLeg]);
  useEffect(() => setRun(initialRun), [initialRun]);
  useEffect(() => setSession(initialSession), [initialSession]);

  return (
    <>
      <section className="m-section">
        <div className="m-raw-head">
          <div>
            <div className="eyebrow">Request data</div>
            <div className="p-detail">
              {filtered.length.toLocaleString()} of {rows.length.toLocaleString()} requests
            </div>
            <div className="p-detail m-terms">
              Time to first token (TTFT), end-to-end request time (E2E),
              generated tokens per second (tok/s), Transport Layer Security
              (TLS), HPKE, and non-uniform
              memory access (NUMA).
            </div>
          </div>
          <div className="m-filters">
            <label>
              <span>inference path</span>
              <select value={leg} onChange={(event) => setLeg(event.target.value)}>
                <option value="all">all</option>
                {legs.map((value) => (
                  <option key={value} value={value}>
                    {value === "C-direct" ? "Claude direct" : value === "C-proxied" ? "Claude through TEE proxy" : legLabel(value)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>model</span>
              <select value={model} onChange={(event) => setModel(event.target.value)}>
                <option value="all">all</option>
                {models.map((value) => <option key={value}>{value}</option>)}
              </select>
            </label>
            <label>
              <span>run id</span>
              <input
                value={run}
                onChange={(event) => setRun(event.target.value)}
                placeholder="all"
                aria-label="Filter by run ID"
              />
            </label>
          </div>
        </div>
        <div className="m-table-scroll">
          <table className="m-table raw-table">
            <thead>
              <tr>
                <th>run</th><th>path</th><th>model</th><th>mode</th>
                <th className="num">threads</th><th className="num">prompt</th>
                <th className="num">output</th><th className="num">concurrency</th>
                <th className="num">ttft</th><th className="num">tok/s</th>
                <th className="num">e2e</th><th>timestamp</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => {
                const rowKey = `${row.run_id}-${row.ts}`;
                const open = openRequest === rowKey;
                return (
                  <Fragment key={rowKey}>
                    <tr className={open ? "raw-parent-row open" : "raw-parent-row"}>
                      <td>
                        <button
                          className="raw-toggle"
                          type="button"
                          aria-expanded={open}
                          onClick={() => setOpenRequest(open ? null : rowKey)}
                        >
                          {trunc(row.run_id, 7)}
                        </button>
                        {warmups.has(row.run_id) && <span className="warmup-tag">warmup</span>}
                      </td>
                      <td>{row.leg === "C-direct" ? "Claude direct" : row.leg === "C-proxied" ? "Claude proxy" : legLabel(row.leg)}</td><td className="dim">{row.model}</td>
                      <td>{row.sev_mode} / {row.input_mode}</td>
                      <td className="num">{fmtInt(row.threads)}</td>
                      <td className="num">{fmtInt(row.prompt_tokens)}</td>
                      <td className="num">{fmtInt(row.output_tokens)}</td>
                      <td className="num">{fmtInt(row.concurrency)}</td>
                      <td className="num">{fmtMs(row.ttft_ms)}</td>
                      <td className="num">{fmtTok(row.tokens_per_s)}</td>
                      <td className="num">{fmtMs(row.e2e_ms)}</td>
                      <td className="dim">{row.ts}</td>
                    </tr>
                    {open && (
                      <tr className="raw-detail-row">
                        <td colSpan={12}>
                          <pre>{JSON.stringify(row, null, 2)}</pre>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="m-pager">
          <button
            type="button"
            aria-label="Previous measurements page"
            title="Previous page"
            disabled={currentPage === 0}
            onClick={() => setPage(Math.max(0, currentPage - 1))}
          >←</button>
          <span>{currentPage + 1} / {pages}</span>
          <button
            type="button"
            aria-label="Next measurements page"
            title="Next page"
            disabled={currentPage + 1 >= pages}
            onClick={() => setPage(Math.min(pages - 1, currentPage + 1))}
          >→</button>
        </div>
        {doc.request_measurements?.note && (
          <div className="p-note">{doc.request_measurements.note}</div>
        )}
      </section>

      <section className="m-section" id="session-measurements">
        <div className="m-raw-head">
          <div>
            <div className="eyebrow">Session data</div>
            <div className="p-detail">
              {filteredSessions.length.toLocaleString()} of {sessions.length.toLocaleString()} sessions
            </div>
            <div className="p-detail m-terms">
              SEV state and STREAM memory
              bandwidth in gigabytes per second (GB/s).
            </div>
          </div>
          <div className="m-filters">
            <label>
              <span>session id</span>
              <input
                value={session}
                onChange={(event) => setSession(event.target.value)}
                placeholder="all"
                aria-label="Filter by session ID"
              />
            </label>
          </div>
        </div>
        <div className="m-table-scroll">
          <table className="m-table">
            <thead><tr><th>session</th><th>SEV</th><th className="num">STREAM GB/s</th><th>kernel</th><th>timestamp</th></tr></thead>
            <tbody>
              {filteredSessions.map((sessionRow) => {
                const open = openSession === sessionRow.session_id;
                return (
                  <Fragment key={sessionRow.session_id}>
                    <tr className={open ? "raw-parent-row open" : "raw-parent-row"}>
                      <td>
                        <button
                          className="raw-toggle"
                          type="button"
                          aria-expanded={open}
                          onClick={() => setOpenSession(open ? null : sessionRow.session_id)}
                        >
                          {sessionRow.session_id}
                        </button>
                      </td>
                      <td>{sessionRow.sev_mode}</td>
                      <td className="num">{fmtGbs(sessionRow.stream_triad_gbs)}</td>
                      <td className="dim">{sessionRow.kernel}</td>
                      <td className="dim">{sessionRow.ts}</td>
                    </tr>
                    {open && (
                      <tr className="raw-detail-row">
                        <td colSpan={5}>
                          <pre>{JSON.stringify(sessionRow, null, 2)}</pre>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
        {doc.session_measurements?.note && (
          <div className="p-note">{doc.session_measurements.note}</div>
        )}
      </section>
    </>
  );
}

/* ---------- page ---------- */

export default function MeasurementsPage() {
  const [doc, setDoc] = useState<MeasurementsDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState("");
  const [session, setSession] = useState("");

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    setRun(query.get("run") ?? "");
    setSession(query.get("session") ?? "");
    fetch("/measurements.json")
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json() as Promise<MeasurementsDoc>;
      })
      .then(setDoc)
      .catch((e: Error) => setError(e.message));
  }, []);

  const provenance = doc?.provenance ?? {};

  return (
    <div className="frame">
      <Masthead
        active="measurements"
        detail={provenance.measured ? `measured ${provenance.measured}` : undefined}
      />

      <main className="m-scroll">
        <div className="m-wrap">
          {!doc && !error && (
            <div className="m-section">
              <div className="p-detail">fetching /measurements.json…</div>
            </div>
          )}
          {error && (
            <div className="m-section">
              <div className="p-lede">measurements.json not available</div>
              <div className="p-detail">
                GET /measurements.json failed ({error}). The file is generated
                into web/public/ from the run logs; rebuild it and reload.
              </div>
            </div>
          )}
          {doc && (
            <>
              <Hero doc={doc} />
              <SweepChart sweep={doc.thread_sweep} />
              <div className="m-grid2">
                <SnpTwinTable twin={doc.snp_twin} />
                <PricingTable models={doc.models} />
              </div>
              <div className="m-grid2">
                <Onchain oc={doc.onchain_devnet} />
                <Misc doc={doc} />
              </div>
              <TaxTable tax={doc.inference_tax} />
              <AnchorBars a={doc.stream_anchor} />
              <RawMeasurements
                doc={doc}
                initialLeg="all"
                initialRun={run}
                initialSession={session}
              />
              <footer className="m-foot">
                <div className="eyebrow">provenance</div>
                <div className="m-prov">
                  {doc.generated_from && (
                    <span>generated from {doc.generated_from}</span>
                  )}
                  {Object.entries(provenance).map(([k, v]) => (
                    <span key={k}>
                      {k.replace(/_/g, " ")}: {v}
                    </span>
                  ))}
                </div>
              </footer>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
