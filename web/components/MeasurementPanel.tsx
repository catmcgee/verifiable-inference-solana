"use client";

import type { AttestationDoc, Metrics, ModelInfo, Receipt } from "@/lib/api";
import {
  DASH,
  fmtInt,
  fmtPrice,
  fmtUsdc,
  msParts,
  fmtRate,
  trunc,
} from "@/lib/format";
import { SERVER } from "@/lib/api";
import {
  explorerUrl,
  gradeLabel,
  REGISTRY_PROGRAM,
  sevLabel,
} from "@/lib/labels";

export interface SessionTotals {
  requests: number;
  tokensIn: number;
  tokensOut: number;
  costUsdc: number;
  unpricedResponses: number;
}

function Meter({
  label,
  value,
  unit,
}: {
  label: string;
  value: string;
  unit?: string;
}) {
  const na = value === DASH;
  return (
    <div>
      <div className="meter-label">{label}</div>
      <div className={`meter-value${na ? " na" : ""}`}>
        {value}
        {!na && unit && <span className="meter-unit">{unit}</span>}
      </div>
    </div>
  );
}

function LastResponse({ m }: { m: Metrics | null }) {
  const ttft = msParts(m?.ttft_ms);
  const itl = msParts(m?.itl_ms_p50);
  const e2e = msParts(m?.e2e_ms);
  return (
    <section className="p-section">
      <div className="eyebrow">last response</div>
      <div className="meters">
        <Meter label="ttft" value={ttft.value} unit={ttft.unit} />
        <Meter
          label="throughput"
          value={m?.tokens_per_s != null ? fmtRate(m.tokens_per_s) : DASH}
          unit="tok/s"
        />
        <Meter label="itl p50" value={itl.value} unit={itl.unit} />
        <Meter label="e2e" value={e2e.value} unit={e2e.unit} />
      </div>
    </section>
  );
}

function Execution({ m }: { m: Metrics | null }) {
  const sev = sevLabel(m?.sev_mode);
  return (
    <section className="p-section">
      <div className="eyebrow">execution</div>
      {sev ? (
        <>
          <div className="p-lede">{sev.label}</div>
          <div className="p-detail">{sev.detail}</div>
        </>
      ) : (
        <div className="p-detail">
          No response yet; sev_mode is reported per response.
        </div>
      )}
      <dl className="kv">
        <dt>sev_mode</dt>
        <dd className={m?.sev_mode ? "" : "na"}>{m?.sev_mode ?? DASH}</dd>
        <dt>backend</dt>
        <dd className={m?.backend ? "" : "na"}>{m?.backend ?? DASH}</dd>
      </dl>
    </section>
  );
}

function Attestation({
  att,
  error,
  loading,
  onRefetch,
}: {
  att: AttestationDoc | null;
  error: string | null;
  loading: boolean;
  onRefetch: () => void;
}) {
  return (
    <section className="p-section">
      <div className="section-head">
        <div className="eyebrow">attestation</div>
        <button type="button" className="p-refetch" onClick={onRefetch}>
          refetch
        </button>
      </div>
      {loading && <div className="p-detail">fetching /v1/attestation…</div>}
      {error && !loading && (
        // network failure OR a 5xx from the Next /vinfer proxy both mean the
        // upstream vinfer server is unreachable — show the calm note for both.
        (error.includes("no route to server") || error.includes("Failed to fetch") ||
         /\b5\d\d\b/.test(error)) ? (
          <>
            <div className="p-lede">no server reachable</div>
            <div className="p-detail">
              Nothing answered at {SERVER}. Attestation renders once a vinfer
              server is running there — start one, or point
              NEXT_PUBLIC_VINFER_URL at a running server and restart the web
              app.
            </div>
          </>
        ) : (
          <div className="p-error">GET /v1/attestation failed: {error}</div>
        )
      )}
      {att && !loading && !error && (
        <>
          <div className="p-lede">
            {gradeLabel(att.grade) ?? DASH}
          </div>
          <dl className="kv">
            <dt>verification</dt>
            <dd className="na">not performed in browser</dd>
            <dt>grade</dt>
            <dd className={att.grade ? "" : "na"}>{att.grade ?? DASH}</dd>
            <dt>sev_mode</dt>
            <dd className={att.sev_mode ? "" : "na"}>{att.sev_mode ?? DASH}</dd>
            <dt>binding</dt>
            <dd>
              {att.binding_version != null ? `v${att.binding_version}` : DASH}
            </dd>
            <dt>registry</dt>
            <dd className="hash">{trunc(att.registry_hash)}</dd>
            <dt>report_data</dt>
            <dd className="hash">{trunc(att.report_data)}</dd>
            <dt>enclave key</dt>
            <dd className="hash">{trunc(att.enclave_pubkey_b64, 8)}</dd>
            <dt>measurement</dt>
            <dd className={att.snp_measurement ? "hash" : "na"}>
              {att.snp_measurement ? trunc(att.snp_measurement) : "none"}
            </dd>
            <dt>snp report</dt>
            <dd className={att.snp_report_b64 ? "hash" : "na"}>
              {att.snp_report_b64 ? "present (b64)" : "none"}
            </dd>
          </dl>
          {att.note && <div className="p-note">{att.note}</div>}
        </>
      )}
    </section>
  );
}

function ReceiptSection({
  receipt,
  registryHash,
}: {
  receipt: Receipt | null;
  registryHash: string | null;
}) {
  const pda = receipt?.attestation_pda;
  return (
    <section className="p-section">
      <div className="eyebrow">receipt</div>
      {receipt ? (
        <>
          <dl className="kv">
            <dt>id</dt>
            <dd className="hash">{receipt.receipt_id ?? DASH}</dd>
            <dt>prompt</dt>
            <dd className="hash">{trunc(receipt.prompt_hash)}</dd>
            <dt>response</dt>
            <dd className="hash">{trunc(receipt.response_hash)}</dd>
            <dt>model</dt>
            <dd className="hash">{trunc(receipt.model_hash)}</dd>
            <dt>signed</dt>
            <dd>
              {receipt.timestamp != null
                ? new Date(receipt.timestamp * 1000).toISOString()
                : DASH}
            </dd>
            {registryHash && (
              <>
                <dt>registry</dt>
                <dd className="hash">{trunc(registryHash)}</dd>
              </>
            )}
          </dl>
          <div className="p-note">
            <a
              href={explorerUrl(pda ?? REGISTRY_PROGRAM)}
              target="_blank"
              rel="noreferrer"
            >
              {pda
                ? "attestation PDA on Solana explorer (devnet)"
                : "attestation registry program on Solana explorer (devnet)"}
            </a>
          </div>
        </>
      ) : (
        <div className="p-detail">
          No receipt yet; one is signed per response.
        </div>
      )}
    </section>
  );
}

function Session({
  totals,
  model,
}: {
  totals: SessionTotals;
  model: ModelInfo | null;
}) {
  const priced =
    model &&
    model.price_per_1m_in_usdc != null &&
    model.price_per_1m_out_usdc != null;
  return (
    <section className="p-section">
      <div className="eyebrow">session</div>
      <dl className="kv">
        <dt>requests</dt>
        <dd>{fmtInt(totals.requests)}</dd>
        <dt>tokens in</dt>
        <dd>{fmtInt(totals.tokensIn)}</dd>
        <dt>tokens out</dt>
        <dd>{fmtInt(totals.tokensOut)}</dd>
        <dt>est. cost</dt>
        <dd>
          {totals.requests === 0 ||
          totals.unpricedResponses === totals.requests
            ? DASH
            : `${fmtUsdc(totals.costUsdc)} USDC`}
        </dd>
      </dl>
      <div className="p-note">
        Estimate: token counts × registry prices
        {priced
          ? ` (${fmtPrice(model.price_per_1m_in_usdc)} in / ${fmtPrice(model.price_per_1m_out_usdc)} out per 1M for ${model.id}).`
          : "."}
        {totals.unpricedResponses > 0 &&
          ` ${totals.unpricedResponses} response${totals.unpricedResponses === 1 ? "" : "s"} had no registry price and ${totals.unpricedResponses === 1 ? "is" : "are"} excluded.`}
      </div>
    </section>
  );
}

export function MeasurementPanel({
  metrics,
  receipt,
  registryHash,
  attestation,
  attestationError,
  attestationLoading,
  onRefetchAttestation,
  totals,
  model,
}: {
  metrics: Metrics | null;
  receipt: Receipt | null;
  registryHash: string | null;
  attestation: AttestationDoc | null;
  attestationError: string | null;
  attestationLoading: boolean;
  onRefetchAttestation: () => void;
  totals: SessionTotals;
  model: ModelInfo | null;
}) {
  return (
    <aside className="panel" aria-label="Live measurement">
      <LastResponse m={metrics} />
      <Execution m={metrics} />
      <Attestation
        att={attestation}
        error={attestationError}
        loading={attestationLoading}
        onRefetch={onRefetchAttestation}
      />
      <ReceiptSection receipt={receipt} registryHash={registryHash} />
      <Session totals={totals} model={model} />
    </aside>
  );
}
