"use client";

import { useEffect, useRef } from "react";
import type { Metrics, Receipt } from "@/lib/api";
import { fmtClock, fmtMs, fmtRate, DASH } from "@/lib/format";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  ts: number;
  model?: string;
  metrics?: Metrics;
  receipt?: Receipt;
  error?: boolean;
}

function MetaLine({ m, receiptId }: { m?: Metrics; receiptId?: string }) {
  if (!m && !receiptId) return null;
  return (
    <div className="msg-meta">
      {m && (
        <>
          <span>
            ttft <span className="v">{fmtMs(m.ttft_ms)}</span>
          </span>
          <span>
            <span className="v">{m.tokens_per_s != null ? fmtRate(m.tokens_per_s) : DASH}</span>{" "}
            tok/s
          </span>
          <span>
            itl p50 <span className="v">{fmtMs(m.itl_ms_p50)}</span>
          </span>
          <span>
            e2e <span className="v">{fmtMs(m.e2e_ms)}</span>
          </span>
        </>
      )}
      {receiptId && (
        <span>
          receipt <span className="r">{receiptId}</span>
        </span>
      )}
    </div>
  );
}

export function MessageList({
  messages,
  pending,
  pendingModel,
}: {
  messages: ChatMessage[];
  pending: boolean;
  pendingModel: string | null;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, pending]);

  return (
    <div className="messages">
      {messages.length === 0 && !pending && (
        <div className="empty">
          <div className="eyebrow">no requests yet</div>
          <p>
            Pick a leg and a model, send a prompt. Every response comes back
            with its measurements and a signed receipt; the panel shows what
            the server reported — nothing more.
          </p>
        </div>
      )}
      {messages.map((msg, i) => (
        <div
          key={i}
          className={`msg ${msg.role}${msg.error ? " error" : ""}`}
        >
          <div className="msg-head">
            <span className="eyebrow who">
              {msg.role === "user"
                ? "you"
                : msg.error
                  ? "server"
                  : `model · ${msg.model ?? DASH}`}
            </span>
            <span className="msg-time">{fmtClock(msg.ts)}</span>
          </div>
          <div className="msg-body">{msg.content}</div>
          {msg.role === "assistant" && !msg.error && (
            <MetaLine m={msg.metrics} receiptId={msg.receipt?.receipt_id} />
          )}
        </div>
      ))}
      {pending && (
        <div className="genline" aria-live="polite">
          <div className="genline-text">
            generating on {pendingModel ?? DASH} — v1 is non-streaming; the
            response renders when the run completes.
          </div>
          <div className="sweep" />
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}

export function Composer({
  input,
  onInput,
  maxTokens,
  onMaxTokens,
  onSend,
  disabled,
  pending,
}: {
  input: string;
  onInput: (v: string) => void;
  maxTokens: number;
  onMaxTokens: (v: number) => void;
  onSend: () => void;
  disabled: boolean;
  pending: boolean;
}) {
  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault();
        onSend();
      }}
    >
      <textarea
        value={input}
        onChange={(e) => onInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSend();
          }
        }}
        placeholder="prompt"
        rows={2}
        aria-label="Prompt"
      />
      <label className="maxtok">
        <span className="eyebrow">max tokens</span>
        <input
          type="number"
          min={1}
          max={4096}
          value={maxTokens}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10);
            if (!Number.isNaN(n)) onMaxTokens(Math.min(4096, Math.max(1, n)));
          }}
          aria-label="Max tokens"
        />
      </label>
      <button type="submit" className="run-btn" disabled={disabled}>
        {pending ? "running" : "run"}
      </button>
    </form>
  );
}
