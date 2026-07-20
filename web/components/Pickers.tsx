"use client";

import { useEffect, useRef } from "react";
import type { LiveLeg, ModelInfo } from "@/lib/api";
import { fmtPrice } from "@/lib/format";
import { LEGS } from "@/lib/labels";

export function LegPicker({
  leg,
  onChange,
  disabled = false,
}: {
  leg: LiveLeg;
  onChange: (leg: LiveLeg) => void;
  disabled?: boolean;
}) {
  const selectedRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest", inline: "center" });
  }, [leg]);
  return (
    <div className="leg-group" role="group" aria-label="Inference trust model">
      {LEGS.map((l) => (
        <button
          key={l.id}
          ref={leg === l.id ? selectedRef : undefined}
          type="button"
          className="leg-btn"
          aria-pressed={leg === l.id}
          aria-controls="leg-content"
          title={l.desc}
          disabled={disabled}
          onClick={() => onChange(l.id)}
        >
          {l.label}
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
        VINFER_ORIGIN_URL at it.
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
          data-model={m.id}
          aria-pressed={selected === m.id}
          disabled={m.status !== "available"}
          onClick={() => onSelect(m.id)}
        >
          <div className="model-chip-id">
            <span className="model-dot" aria-hidden="true" />
            {m.id}
          </div>
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
