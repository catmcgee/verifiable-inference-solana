"use client";

import { useEffect, useRef, useState } from "react";
import { ChartNoAxesCombined, LogIn, LogOut, Send } from "lucide-react";
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

export function AccessBar({
  required,
  authenticated,
  loading,
  error,
  onLogin,
  onLogout,
}: {
  required: boolean;
  authenticated: boolean;
  loading: boolean;
  error: string | null;
  onLogin: (accessCode: string) => Promise<boolean>;
  onLogout: () => Promise<void>;
}) {
  const [accessCode, setAccessCode] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (!required && authenticated) return null;

  if (authenticated) {
    return (
      <div className="accessbar">
        <span className="access-state">test session active</span>
        <button type="button" onClick={() => void onLogout()}>
          <LogOut size={14} aria-hidden="true" />
          sign out
        </button>
      </div>
    );
  }

  return (
    <form
      className="accessbar access-login"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!accessCode || submitting) return;
        setSubmitting(true);
        const accepted = await onLogin(accessCode);
        setSubmitting(false);
        if (accepted) setAccessCode("");
      }}
    >
      <label htmlFor="access-code">test access</label>
      <input
        id="access-code"
        type="password"
        value={accessCode}
        onChange={(event) => setAccessCode(event.target.value)}
        placeholder="access code"
        autoComplete="one-time-code"
        inputMode="text"
        spellCheck={false}
        disabled={loading || submitting}
      />
      <button type="submit" disabled={!accessCode || loading || submitting}>
        <LogIn size={14} aria-hidden="true" />
        {submitting ? "checking" : "sign in"}
      </button>
      {error && <span className="access-error">{error}</span>}
    </form>
  );
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
  sealed,
}: {
  messages: ChatMessage[];
  pending: boolean;
  pendingModel: string | null;
  sealed: boolean;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, pending]);

  return (
    <div className="messages">
      {messages.length === 0 && !pending && (
        <div className="empty">
          <div className="empty-visual" aria-hidden="true">
            <ChartNoAxesCombined />
          </div>
          <div className="eyebrow">No requests yet</div>
          <p>
            Choose how to run inference, choose a model, then send a prompt.
            Each response includes timing, cost, attestation status, and a receipt.
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
            {sealed ? "sealed inference from" : "streaming from"} {pendingModel ?? DASH}
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
        <Send size={16} aria-hidden="true" />
        {pending ? "running" : "run"}
      </button>
    </form>
  );
}
