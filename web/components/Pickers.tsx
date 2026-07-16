"use client";

import type { ModelInfo } from "@/lib/api";
import { fmtPrice } from "@/lib/format";
import { LEGS } from "@/lib/labels";

export function LegPicker({
  leg,
  onChange,
}: {
  leg: string;
  onChange: (leg: string) => void;
}) {
  return (
    <div className="leg-group" role="group" aria-label="Trust leg">
      <span className="eyebrow">leg</span>
      {LEGS.map((l) => (
        <button
          key={l.id}
          type="button"
          className="leg-btn"
          aria-pressed={leg === l.id}
          disabled={l.disabled}
          title={l.desc}
          onClick={() => !l.disabled && onChange(l.id)}
        >
          {l.id}
        </button>
      ))}
    </div>
  );
}

export function ModelPicker({
  models,
  selected,
  onSelect,
  loading,
  error,
}: {
  models: ModelInfo[];
  selected: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
  error: string | null;
}) {
  if (error) {
    return (
      <div className="picker-error">
        GET /v1/models failed: {error}. Start the server, or point
        NEXT_PUBLIC_VINFER_URL at it.
      </div>
    );
  }
  if (loading) {
    return <div className="picker-note">fetching /v1/models…</div>;
  }
  if (models.length === 0) {
    return (
      <div className="picker-note">
        No models registered for this leg on this server.
      </div>
    );
  }
  return (
    <div className="model-strip" role="group" aria-label="Model">
      {models.map((m) => (
        <button
          key={m.id}
          type="button"
          className="model-chip"
          aria-pressed={selected === m.id}
          onClick={() => onSelect(m.id)}
        >
          <div className="model-chip-id">{m.id}</div>
          <div className="model-chip-sub">
            {m.quant ?? "—"} · {m.runtime ?? "—"} ·{" "}
            {m.price_per_1m_in_usdc != null && m.price_per_1m_out_usdc != null
              ? `${fmtPrice(m.price_per_1m_in_usdc)}/${fmtPrice(m.price_per_1m_out_usdc)} USDC per 1M`
              : "unpriced"}
            {m.status !== "available" && (
              <>
                {" "}
                · <span className="pending">{m.status}</span>
              </>
            )}
          </div>
        </button>
      ))}
    </div>
  );
}
