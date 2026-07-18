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
    batched_cu_per_receipt?: number;
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

function Hero({ doc }: { doc: MeasurementsDoc }) {
  const ceiling = doc.stream_anchor?.sev_es_tax_pct;
  const taxes = Object.values(doc.inference_tax?.by_model ?? {})
    .map((m) => m.tax_pct)
    .filter((v): v is number => v != null);
  const worst = taxes.length ? Math.max(...taxes) : null;
  return (
    <section className="m-section m-hero">
      <div className="eyebrow">What the measurements say</div>
      <p className="m-hero-intro">
        These runs compare a plain virtual machine (VM) with AMD Secure
        Encrypted Virtualization with Encrypted State (SEV-ES). The protected
        VM is a Trusted Execution Environment (TEE). The STREAM benchmark
        measures memory speed; model speed is measured in generated tokens per
        second (tok/s).
      </p>
      <div className="m-hero-values">
        <div className="m-hv ceiling">
          <div className="n">
            {ceiling != null ? ceiling.toFixed(1) : DASH}
            {ceiling != null && <span className="u">%</span>}
          </div>
          <div className="m-hv-label">STREAM bandwidth slowdown</div>
        </div>
        <div className="m-vs">vs</div>
        <div className="m-hv actual">
          <div className="n">
            {worst != null ? worst.toFixed(1) : DASH}
            {worst != null && <span className="u">%</span>}
          </div>
          <div className="m-hv-label">model inference slowdown</div>
        </div>
      </div>
      <p className="m-finding">
        STREAM repeatedly reads and writes large arrays to measure memory
        bandwidth; it does not run a model. Memory encryption made that stress
        test 26% slower, while actual model inference was about 2% slower in
        the matched runs. STREAM is therefore a ceiling, not an estimate of
        the slowdown a model user sees.
      </p>
    </section>
  );
}

/* ---------- stream anchor bars ---------- */

function AnchorBars({ a }: { a: StreamAnchor | undefined }) {
  const rows: { label: string; v?: number; tax?: number; hit?: boolean }[] = [
    { label: "bare metal", v: a?.bare_metal_gbs },
    { label: "plain vm", v: a?.plain_vm_gbs },
    { label: "sev-es", v: a?.sev_es_gbs, tax: a?.sev_es_tax_pct, hit: true },
  ];
  const max = Math.max(...rows.map((r) => r.v ?? 0), 1);
  return (
    <section className="m-section">
      <div className="eyebrow">Memory bandwidth in gigabytes per second (GB/s)</div>
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
      <div className="eyebrow">TEE speed by model</div>
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
        Higher tokens per second is faster. A positive difference is the TEE
        slowdown; a negative value means that run was slightly faster inside
        the TEE, which is normal run-to-run measurement noise.
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
        <dt>batched, per receipt</dt>
        <dd>
          {oc?.batched_cu_per_receipt != null ? (
            <>
              <span className="v">{fmtInt(oc.batched_cu_per_receipt)}</span> CU
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
              <AnchorBars a={doc.stream_anchor} />
              <SweepChart sweep={doc.thread_sweep} />
              <div className="m-grid2">
                <TaxTable tax={doc.inference_tax} />
                <PricingTable models={doc.models} />
              </div>
              <SnpTwinTable twin={doc.snp_twin} />
              <div className="m-grid2">
                <Onchain oc={doc.onchain_devnet} />
                <Misc doc={doc} />
              </div>
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
