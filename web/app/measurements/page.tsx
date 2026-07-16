"use client";

// Measurements view: renders web/public/measurements.json verbatim.
// Every number on this page comes from that file; anything absent is "—".

import { useEffect, useState } from "react";
import Link from "next/link";
import { DASH, fmtInt, fmtMs, trunc } from "@/lib/format";
import { explorerUrl } from "@/lib/labels";

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
  };
  onchain_devnet?: {
    program_id?: string;
    register_attestation_cu?: number;
    post_receipt_cu?: number;
    batched_cu_per_receipt?: number;
    note?: string;
  };
  hpke_overhead_ms?: number;
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
      <div className="eyebrow">the headline — sev-es tax</div>
      <div className="m-hero-values">
        <div className="m-hv ceiling">
          <div className="n">
            {ceiling != null ? ceiling.toFixed(1) : DASH}
            {ceiling != null && <span className="u">%</span>}
          </div>
          <div className="m-hv-label">stream — pure-bandwidth ceiling</div>
        </div>
        <div className="m-vs">vs</div>
        <div className="m-hv actual">
          <div className="n">
            {worst != null ? worst.toFixed(1) : DASH}
            {worst != null && <span className="u">%</span>}
          </div>
          <div className="m-hv-label">inference — worst measured model</div>
        </div>
      </div>
      <p className="m-finding">{doc.inference_tax?.finding ?? DASH}</p>
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
      <div className="eyebrow">tee tax anchor — stream triad bandwidth</div>
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
      {a?.note && <div className="p-note">{a.note}</div>}
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
        <div className="eyebrow">thread-saturation sweep</div>
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
        thread-saturation sweep — decode throughput vs threads
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
      {sweep?.note && <div className="p-note">{sweep.note}</div>}
    </section>
  );
}

/* ---------- tables ---------- */

function TaxTable({ tax }: { tax: InferenceTax | undefined }) {
  const rows = Object.entries(tax?.by_model ?? {});
  return (
    <section className="m-section">
      <div className="eyebrow">per-model inference tax</div>
      {rows.length === 0 ? (
        <div className="p-detail">no per-model rows.</div>
      ) : (
        <table className="m-table">
          <thead>
            <tr>
              <th>model</th>
              <th className="num">plain vm tok/s</th>
              <th className="num">sev-es tok/s</th>
              <th className="num">tax</th>
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
    </section>
  );
}

function PricingTable({ models }: { models: PricedModel[] | undefined }) {
  const rows = models ?? [];
  return (
    <section className="m-section">
      <div className="eyebrow">registry pricing — usdc per 1m tokens</div>
      {rows.length === 0 ? (
        <div className="p-detail">no models listed.</div>
      ) : (
        <table className="m-table">
          <thead>
            <tr>
              <th>model</th>
              <th>quant</th>
              <th className="num">in</th>
              <th className="num">out</th>
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
    </section>
  );
}

/* ---------- on-chain + misc ---------- */

function Onchain({ oc }: { oc: MeasurementsDoc["onchain_devnet"] }) {
  return (
    <section className="m-section">
      <div className="eyebrow">on-chain economics — devnet</div>
      <dl className="kv wide">
        <dt>register_attestation</dt>
        <dd>
          {oc?.register_attestation_cu != null ? (
            <>
              <span className="v">{fmtInt(oc.register_attestation_cu)}</span> CU
            </>
          ) : (
            DASH
          )}
        </dd>
        <dt>post_receipt</dt>
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
      <div className="eyebrow">misc</div>
      <dl className="kv wide">
        <dt>hpke overhead</dt>
        <dd>
          {doc.hpke_overhead_ms != null ? (
            <>
              <span className="v">{doc.hpke_overhead_ms}</span> ms per request
            </>
          ) : (
            DASH
          )}
        </dd>
        <dt>leg c api model</dt>
        <dd className={c?.model ? "" : "na"}>{c?.model ?? DASH}</dd>
        <dt>leg c ttft median</dt>
        <dd>
          {c?.ttft_ms_median != null ? (
            <span className="v">{fmtMs(c.ttft_ms_median)}</span>
          ) : (
            DASH
          )}
        </dd>
        <dt>leg c e2e median</dt>
        <dd>
          {c?.e2e_ms_median != null ? (
            <span className="v">{fmtMs(c.e2e_ms_median)}</span>
          ) : (
            DASH
          )}
        </dd>
        <dt>leg c n</dt>
        <dd className={c?.n != null ? "" : "na"}>{fmtInt(c?.n)}</dd>
      </dl>
    </section>
  );
}

/* ---------- page ---------- */

export default function MeasurementsPage() {
  const [doc, setDoc] = useState<MeasurementsDoc | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
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
      <header className="masthead">
        <div className="wordmark">
          verified-inference <b>/ measurements</b>
        </div>
        <nav className="masthead-nav" aria-label="Views">
          <Link href="/">console</Link>
          <Link href="/measurements" aria-current="page">
            measurements
          </Link>
        </nav>
        <div className="masthead-endpoint">
          {provenance.measured ? `measured ${provenance.measured}` : ""}
        </div>
      </header>

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
              <div className="m-grid2">
                <Onchain oc={doc.onchain_devnet} />
                <Misc doc={doc} />
              </div>
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
