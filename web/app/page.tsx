"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getAttestation,
  getModels,
  postChat,
  SERVER,
  type AttestationDoc,
  type Metrics,
  type ModelInfo,
  type Receipt,
} from "@/lib/api";
import { LEGS } from "@/lib/labels";
import { LegPicker, ModelPicker } from "@/components/Pickers";
import { Composer, MessageList, type ChatMessage } from "@/components/Chat";
import {
  MeasurementPanel,
  type SessionTotals,
} from "@/components/MeasurementPanel";

const EMPTY_TOTALS: SessionTotals = {
  requests: 0,
  tokensIn: 0,
  tokensOut: 0,
  costUsdc: 0,
  unpricedResponses: 0,
};

export default function Page() {
  // registry
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);

  // attestation
  const [attestation, setAttestation] = useState<AttestationDoc | null>(null);
  const [attLoading, setAttLoading] = useState(true);
  const [attError, setAttError] = useState<string | null>(null);

  // selection
  const [leg, setLeg] = useState("A");
  const [modelId, setModelId] = useState<string | null>(null);

  // chat
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [maxTokens, setMaxTokens] = useState(256);
  const [pending, setPending] = useState(false);

  // panel
  const [lastMetrics, setLastMetrics] = useState<Metrics | null>(null);
  const [lastReceipt, setLastReceipt] = useState<Receipt | null>(null);
  const [registryHash, setRegistryHash] = useState<string | null>(null);
  const [totals, setTotals] = useState<SessionTotals>(EMPTY_TOTALS);

  const pendingRef = useRef(false);

  const loadAttestation = useCallback(() => {
    setAttLoading(true);
    setAttError(null);
    getAttestation()
      .then(setAttestation)
      .catch((e: Error) => setAttError(e.message))
      .finally(() => setAttLoading(false));
  }, []);

  useEffect(() => {
    getModels()
      .then((data) => {
        setModels(data);
        setModelsError(null);
      })
      .catch((e: Error) => setModelsError(e.message))
      .finally(() => setModelsLoading(false));
    loadAttestation();
  }, [loadAttestation]);

  const legModels = useMemo(
    () => models.filter((m) => (m.legs ?? []).includes(leg)),
    [models, leg],
  );

  // keep the selection valid for the active leg
  useEffect(() => {
    if (!legModels.some((m) => m.id === modelId)) {
      setModelId(legModels[0]?.id ?? null);
    }
  }, [legModels, modelId]);

  const model = legModels.find((m) => m.id === modelId) ?? null;
  const activeLeg = LEGS.find((l) => l.id === leg);
  const legD = LEGS.find((l) => l.id === "D");

  async function send() {
    const content = input.trim();
    if (!content || pendingRef.current || !model) return;
    const history = [...messages, { role: "user" as const, content, ts: Date.now() }];
    setMessages(history);
    setInput("");
    setPending(true);
    pendingRef.current = true;
    try {
      const resp = await postChat(
        model.id,
        history.map((m) => ({ role: m.role, content: m.content })),
        maxTokens,
      );
      const metrics = resp.x_vinfer?.metrics ?? null;
      const receipt = resp.x_vinfer?.receipt ?? null;
      const text = resp.choices?.[0]?.message?.content ?? "";
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: text,
          ts: Date.now(),
          model: resp.model ?? model.id,
          metrics: metrics ?? undefined,
          receipt: receipt ?? undefined,
        },
      ]);
      setLastMetrics(metrics);
      setLastReceipt(receipt);
      setRegistryHash(resp.x_vinfer?.registry_hash ?? null);

      const tokIn = resp.usage?.prompt_tokens ?? 0;
      const tokOut = resp.usage?.completion_tokens ?? 0;
      const priced =
        model.price_per_1m_in_usdc != null &&
        model.price_per_1m_out_usdc != null;
      const cost = priced
        ? (tokIn * (model.price_per_1m_in_usdc as number)) / 1_000_000 +
          (tokOut * (model.price_per_1m_out_usdc as number)) / 1_000_000
        : 0;
      setTotals((t) => ({
        requests: t.requests + 1,
        tokensIn: t.tokensIn + tokIn,
        tokensOut: t.tokensOut + tokOut,
        costUsdc: t.costUsdc + cost,
        unpricedResponses: t.unpricedResponses + (priced ? 0 : 1),
      }));
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `request failed: ${e instanceof Error ? e.message : String(e)}`,
          ts: Date.now(),
          error: true,
        },
      ]);
    } finally {
      setPending(false);
      pendingRef.current = false;
    }
  }

  return (
    <div className="frame">
      <header className="masthead">
        <div className="wordmark">
          verified-inference <b>/ measurement console</b>
        </div>
        <div className="masthead-endpoint">{SERVER}</div>
      </header>

      <div className="pickerbar">
        <div className="picker-row">
          <LegPicker leg={leg} onChange={setLeg} />
          <ModelPicker
            models={legModels}
            selected={modelId}
            onSelect={setModelId}
            loading={modelsLoading}
            error={modelsError}
          />
        </div>
        {!modelsError && (
          <div className="picker-note">
            {activeLeg && (
              <>
                leg {activeLeg.id}: {activeLeg.desc}
              </>
            )}{" "}
            {legD && (
              <span className="deferred">
                leg D disabled — {legD.desc}
              </span>
            )}
          </div>
        )}
      </div>

      <div className="body">
        <main className="chat">
          <MessageList
            messages={messages}
            pending={pending}
            pendingModel={model?.id ?? null}
          />
          <Composer
            input={input}
            onInput={setInput}
            maxTokens={maxTokens}
            onMaxTokens={setMaxTokens}
            onSend={send}
            disabled={pending || !model || input.trim().length === 0}
            pending={pending}
          />
        </main>
        <MeasurementPanel
          metrics={lastMetrics}
          receipt={lastReceipt}
          registryHash={registryHash}
          attestation={attestation}
          attestationError={attError}
          attestationLoading={attLoading}
          onRefetchAttestation={loadAttestation}
          totals={totals}
          model={model}
        />
      </div>
    </div>
  );
}
