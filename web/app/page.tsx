"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  createAuthSession,
  deleteAuthSession,
  getAttestation,
  getAuthSession,
  getModels,
  postChatE2E,
  postChatStream,
  SERVER,
  type AttestationDoc,
  type AuthSession,
  type Metrics,
  type ModelInfo,
  type Receipt,
  type LiveLeg,
} from "@/lib/api";
import { LEGS } from "@/lib/labels";
import { LegPicker, ModelPicker } from "@/components/Pickers";
import { LegScope } from "@/components/LegScope";
import { Masthead } from "@/components/Masthead";
import {
  AccessBar,
  Composer,
  MessageList,
  type ChatMessage,
} from "@/components/Chat";
import {
  MeasurementPanel,
  type SessionTotals,
} from "@/components/MeasurementPanel";
import {
  verifyReceiptContent,
  verifyInBrowser,
  type BrowserVerification,
} from "@/lib/attestationVerifier";

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
  const [verification, setVerification] = useState<BrowserVerification | null>(null);
  const [verificationLoading, setVerificationLoading] = useState(false);

  // browser test access
  const [auth, setAuth] = useState<AuthSession | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);

  // selection
  const [leg, setLeg] = useState("B");
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
  const attestationRequestRef = useRef(0);

  const liveLeg: LiveLeg | null = leg === "A" || leg === "B" || leg === "C" ? leg : null;

  const loadAttestation = useCallback(() => {
    if (!liveLeg) return;
    const requestId = ++attestationRequestRef.current;
    setAttLoading(true);
    setAttError(null);
    getAttestation(liveLeg)
      .then((document) => {
        if (requestId === attestationRequestRef.current) {
          setVerification(null);
          setAttestation(document);
        }
      })
      .catch((e: Error) => {
        if (requestId === attestationRequestRef.current) {
          setAttError(e.message);
        }
      })
      .finally(() => {
        if (requestId === attestationRequestRef.current) {
          setAttLoading(false);
        }
      });
  }, [liveLeg]);

  useEffect(() => {
    if (!liveLeg) return;
    let cancelled = false;
    setModelsLoading(true);
    setModelsError(null);
    setAttestation(null);
    setLastReceipt(null);
    setLastMetrics(null);
    setRegistryHash(null);
    getModels(liveLeg)
      .then((data) => {
        if (!cancelled) {
          setModels(data);
          setModelsError(null);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setModelsError(e.message);
      })
      .finally(() => {
        if (!cancelled) setModelsLoading(false);
      });
    loadAttestation();
    setAuthLoading(true);
    getAuthSession(liveLeg)
      .then((session) => {
        if (!cancelled) {
          setAuth(session);
          setAuthError(null);
        }
      })
      .catch((e: Error) => {
        if (!cancelled) setAuthError(e.message);
      })
      .finally(() => {
        if (!cancelled) setAuthLoading(false);
      });
    return () => {
      cancelled = true;
      attestationRequestRef.current += 1;
    };
  }, [liveLeg, loadAttestation]);

  useEffect(() => {
    let cancelled = false;
    if (!attestation) {
      setVerification(null);
      return;
    }
    setVerificationLoading(true);
    verifyInBrowser(attestation, lastReceipt)
      .then((result) => {
        if (!cancelled) setVerification(result);
      })
      .finally(() => {
        if (!cancelled) setVerificationLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [attestation, lastReceipt]);

  async function login(accessCode: string): Promise<boolean> {
    if (!liveLeg) return false;
    setAuthError(null);
    try {
      const session = await createAuthSession(accessCode, liveLeg);
      setAuth(session);
      return session.authenticated;
    } catch (e) {
      setAuthError(e instanceof Error ? e.message : String(e));
      return false;
    }
  }

  async function logout(): Promise<void> {
    if (!liveLeg) return;
    setAuthError(null);
    try {
      await deleteAuthSession(liveLeg);
      setAuth({ required: true, authenticated: false, mode: null });
    } catch (e) {
      setAuthError(e instanceof Error ? e.message : String(e));
    }
  }

  const legModels = useMemo(
    () => models.filter((m) => m.status === "available" && (m.legs ?? []).includes(leg)),
    [models, leg],
  );

  // keep the selection valid for the active leg
  useEffect(() => {
    if (!liveLeg) return;
    if (!legModels.some((m) => m.id === modelId)) {
      setModelId(legModels[0]?.id ?? null);
    }
  }, [liveLeg, legModels, modelId]);

  const model = liveLeg ? legModels.find((m) => m.id === modelId) ?? null : null;
  const activeLeg = LEGS.find((l) => l.id === leg);

  async function send() {
    const content = input.trim();
    if (!content || pendingRef.current || !model || !liveLeg) return;
    if (liveLeg === "B" && (!attestation || !verification?.attestationTrusted)) {
      return;
    }
    const history = [...messages, { role: "user" as const, content, ts: Date.now() }];
    setMessages([
      ...history,
      { role: "assistant", content: "", ts: Date.now(), model: model.id },
    ]);
    setInput("");
    setPending(true);
    pendingRef.current = true;
    try {
      const requestMessages = history.map((message) => ({
        role: message.role,
        content: message.content,
      }));
      const resp = liveLeg === "B"
        ? await postChatE2E(
            model.id,
            requestMessages,
            maxTokens,
            attestation!,
            (delta) => {
              setMessages((prev) => prev.map((message, index) =>
                index === prev.length - 1
                  ? { ...message, content: message.content + delta }
                  : message,
              ));
            },
          )
        : await postChatStream(
            liveLeg,
            model.id,
            requestMessages,
            maxTokens,
            (delta) => {
              setMessages((prev) => prev.map((message, index) =>
                index === prev.length - 1
                  ? { ...message, content: message.content + delta }
                  : message,
              ));
            },
          );
      const metrics = resp.x_vinfer?.metrics ?? null;
      const receipt = resp.x_vinfer?.receipt ?? null;
      const responseContent = resp.choices[0]?.message.content ?? "";
      if (!receipt) throw new Error("response ended without a signed receipt");
      await verifyReceiptContent(
        receipt,
        model.id,
        requestMessages,
        maxTokens,
        responseContent,
      );
      setMessages((prev) => prev.map((message, index) =>
        index === prev.length - 1
          ? {
              ...message,
              content: liveLeg === "B"
                ? responseContent
                : message.content,
              model: resp.model ?? model.id,
              metrics: metrics ?? undefined,
              receipt: receipt ?? undefined,
            }
          : message,
      ));
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
      if (e instanceof ApiError && e.status === 401) {
        setAuth((current) => ({
          required: current?.required ?? true,
          authenticated: false,
          mode: null,
        }));
      }
      setMessages((prev) => prev.map((message, index) =>
        index === prev.length - 1
          ? {
              role: "assistant",
              content: `request failed: ${e instanceof Error ? e.message : String(e)}`,
              ts: Date.now(),
              error: true,
            }
          : message,
      ));
    } finally {
      setPending(false);
      pendingRef.current = false;
    }
  }

  return (
    <div className="frame">
      <Masthead active="console" detail={SERVER} />

      <div className="pickerbar">
        <div className="picker-row">
          <LegPicker leg={leg} onChange={setLeg} disabled={pending} />
          {liveLeg ? (
            <ModelPicker
              models={legModels}
              selected={modelId}
              onSelect={setModelId}
              loading={modelsLoading}
              error={modelsError}
            />
          ) : (
            <div className={`picker-availability ${activeLeg?.availability ?? ""}`}>
              {activeLeg?.availability === "recorded" ? "recorded only" : "not implemented"}
            </div>
          )}
        </div>
        {!modelsError && (
          <div className="picker-note">
            {activeLeg?.desc}
          </div>
        )}
      </div>

      {liveLeg ? <div className="body" id="leg-content">
        <main className="chat">
          <AccessBar
            required={auth?.required ?? true}
            authenticated={auth?.authenticated ?? false}
            loading={authLoading}
            error={authError}
            onLogin={login}
            onLogout={logout}
          />
          <MessageList
            messages={messages}
            pending={pending}
            pendingModel={model?.id ?? null}
            sealed={liveLeg === "B"}
          />
          <Composer
            input={input}
            onInput={setInput}
            maxTokens={maxTokens}
            onMaxTokens={setMaxTokens}
            onSend={send}
            disabled={
              pending ||
              !auth?.authenticated ||
              !model ||
              (liveLeg === "B" && !verification?.attestationTrusted) ||
              input.trim().length === 0
            }
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
          verification={verification}
          verificationLoading={verificationLoading}
          onRefetchAttestation={loadAttestation}
          totals={totals}
          model={model}
        />
      </div> : <LegScope leg={leg} />}
    </div>
  );
}
