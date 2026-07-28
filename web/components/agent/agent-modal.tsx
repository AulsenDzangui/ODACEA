"use client";

// Agent (UI chat, présentation seule).
// Modale plutôt que page dédiée : montée en permanence dans app/page.tsx et
// pilotée par `open`/`onOpenChange`, elle reste disponible en un clic depuis
// n'importe quelle étape du wizard sans navigation ni perte de conversation
// (l'état local survit à la fermeture, comme SettingsModal).
// L'archiviste crée une session serveur depuis son CSV puis dialogue avec
// AGT-001 pour **explorer et rechercher** dans le vrac. Agent lecture seule :
// aucune capacité de classement, de renommage ni de mémorisation de faits. Le
// CSV ne transite jamais dans un prompt (agent avec outils côté moteur) ; le
// front affiche les appels d'outils et leurs résultats (transparence).

import { useCallback, useEffect, useRef, useState } from "react";
import { Dialog as DialogPrimitive } from "radix-ui";
import {
  Check,
  Copy,
  Loader2,
  RotateCcw,
  Send,
  Square,
  Wrench,
  X,
} from "lucide-react";
import {
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { StreamingMarkdown } from "@/components/streaming-markdown";
import { useT } from "@/lib/i18n";
import { useWizard } from "@/lib/store";
import { DEMO_MODE } from "@/lib/llm/config";
import {
  streamSse,
  formatApiError,
  ApiError,
  mapUsage,
  type ToolEvent,
  type LlmUsage,
} from "@/lib/llm/client-stream";
import {
  createAgentSession,
  deleteAgentSession,
  resetAgentConversation,
  type AgentSessionCreated,
} from "@/lib/llm/agent-client";
import { safeName } from "@/lib/persistence";
import { stringifyCsv } from "@/lib/csv/parse";
import { formatTokens, formatCostEur } from "@/lib/tokens/estimate";

type ToolStep = {
  step: number;
  name: string;
  arguments?: unknown;
  result?: unknown;
};

type ChatEntry =
  | { role: "user"; text: string }
  | {
      role: "assistant";
      text: string;
      tools: ToolStep[];
      notices: string[];
      error?: string;
    };

type SessionState = {
  id: string;
  csvText: string;
  // Référence du `csvOriginal` ayant servi à créer la session. L'agent est lié au
  // projet courant : si cette référence ne correspond plus au CSV chargé (autre
  // projet ouvert), la session est recréée sur le nouveau vrac.
  csvRef: unknown;
  // Rapport d'audit réellement envoyé en contexte (0.6.0), "" si aucun. Sert à
  // (a) recréer une session expirée à l'identique et (b) détecter un changement
  // de décision (toggle basculé, ou rapport apparu/modifié) → recréation.
  auditReport: string;
  // Ce que le backend a confirmé avoir retenu (rapport non vide accepté).
  auditReportUsed: boolean;
  stem: string;
  rows: number;
  ttlS: number;
};

export function AgentModal({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useT().agent;
  const modelId = useWizard((s) => s.modelId);
  const apiKey = useWizard((s) => s.apiKey);
  const baseUrl = useWizard((s) => s.baseUrl);
  const csvOriginal = useWizard((s) => s.csvOriginal);
  const csvFilename = useWizard((s) => s.csvFilename);
  const rapportAudit = useWizard((s) => s.rapportAudit);
  const agentUseAuditReport = useWizard((s) => s.agentUseAuditReport);
  const setAgentUseAuditReport = useWizard((s) => s.setAgentUseAuditReport);

  // Rapport d'audit à injecter selon le toggle : "" quand désactivé ou absent
  // (le backend garde alors le system prompt inchangé). Décision unique, dérivée.
  const desiredAuditReport =
    agentUseAuditReport && rapportAudit.trim() ? rapportAudit : "";
  const hasAuditReport = rapportAudit.trim().length > 0;

  const [session, setSession] = useState<SessionState | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const [entries, setEntries] = useState<ChatEntry[]>([]);
  const [input, setInput] = useState("");
  const [running, setRunning] = useState(false);
  const [recreating, setRecreating] = useState(false);
  const [usageSession, setUsageSession] = useState<LlmUsage | null>(null);
  const [costSession, setCostSession] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Suit le fil : reste calé en bas pendant le streaming.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [entries]);

  const startSession = useCallback(
    async (
      csvText: string,
      stem: string,
      csvRef: unknown,
      auditReport: string,
    ) => {
      setCreating(true);
      setCreateError("");
      try {
        const created: AgentSessionCreated = await createAgentSession({
          csv: csvText,
          auditReport,
        });
        setSession({
          id: created.sessionId,
          csvText,
          csvRef,
          auditReport,
          auditReportUsed: created.auditReportUsed ?? auditReport.length > 0,
          stem,
          rows:
            typeof created.stats?.rowCount === "number"
              ? (created.stats.rowCount as number)
              : 0,
          ttlS: created.ttlS,
        });
        setEntries([]);
        setUsageSession(null);
        setCostSession(null);
      } catch (err) {
        setCreateError(formatApiError(err));
      } finally {
        setCreating(false);
      }
    },
    [],
  );

  /** Recrée la session serveur depuis l'état client et renvoie son id.
   *  Reproduit le **même contexte** (dont le rapport d'audit alors injecté) pour
   *  que le tour relancé après expiration soit identique. */
  const recreateSession = async (prev: SessionState): Promise<string> => {
    setRecreating(true);
    try {
      const created = await createAgentSession({
        csv: prev.csvText,
        auditReport: prev.auditReport,
      });
      setSession({ ...prev, id: created.sessionId });
      return created.sessionId;
    } finally {
      setRecreating(false);
    }
  };

  // Démarre (ou redémarre) la session depuis le CSV du projet courant. Seule
  // source possible : l'agent est lié au projet, plus d'import de CSV tiers.
  // Le rapport d'audit courant est joint selon le toggle (0.6.0).
  const startFromProject = useCallback(() => {
    if (!csvOriginal || csvOriginal.length === 0) return;
    const stem = safeName(csvFilename.replace(/\.csv$/i, "") || "vrac");
    void startSession(
      stringifyCsv(csvOriginal),
      stem,
      csvOriginal,
      desiredAuditReport,
    );
  }, [csvOriginal, csvFilename, startSession, desiredAuditReport]);

  // Démarrage automatique à l'ouverture — plus d'étape de chargement préalable.
  // La session suit le projet courant : on (re)crée dès qu'aucune session n'est
  // liée au CSV actuellement chargé (ouverture, ou changement de projet). Pas de
  // relance auto après une erreur (l'écran d'erreur propose « Réessayer »).
  useEffect(() => {
    if (!open || DEMO_MODE || creating || createError) return;
    if (!csvOriginal || csvOriginal.length === 0) return;
    // Session à jour = liée au CSV courant ET portant la même décision de contexte
    // (rapport d'audit injecté ou non). Un écart sur l'un ou l'autre la recrée.
    if (
      session &&
      session.csvRef === csvOriginal &&
      session.auditReport === desiredAuditReport
    )
      return;
    // Contexte changé (projet chargé, ou décision rapport d'audit : toggle basculé,
    // rapport apparu/modifié) : on libère l'ancienne session serveur avant d'en
    // créer une. Comme un changement de projet, le fil de conversation repart.
    if (session) {
      void deleteAgentSession(session.id);
    }
    startFromProject();
  }, [
    open,
    creating,
    createError,
    csvOriginal,
    session,
    startFromProject,
    desiredAuditReport,
  ]);

  const appendAssistant = (
    update: (last: Extract<ChatEntry, { role: "assistant" }>) => ChatEntry,
  ) => {
    setEntries((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role === "assistant") next[next.length - 1] = update(last);
      return next;
    });
  };

  const runTurn = async (sessionId: string, message: string) => {
    const controller = new AbortController();
    abortRef.current = controller;
    return streamSse(
      "/agt/chat",
      { sessionId, message, model: modelId, apiKey, baseUrl },
      {
        onText: (delta) =>
          appendAssistant((last) => ({ ...last, text: last.text + delta })),
        onNotice: (msg) =>
          appendAssistant((last) => ({
            ...last,
            notices: [...last.notices, msg],
          })),
        onTool: (e: ToolEvent) =>
          appendAssistant((last) => {
            const tools = [...last.tools];
            if (e.kind === "call") {
              tools.push({ step: e.step, name: e.name, arguments: e.arguments });
              return { ...last, tools };
            }
            // Rattache le résultat au PREMIER appel (step, name) encore sans
            // résultat : un même outil peut être appelé plusieurs fois dans une
            // étape (appels parallèles) et matcher sans exiger `result ===
            // undefined` écraserait toujours le premier appel — les suivants
            // restaient avec un spinner qui tournait indéfiniment.
            const idx = tools.findIndex(
              (s) =>
                s.step === e.step &&
                s.name === e.name &&
                s.result === undefined,
            );
            if (idx >= 0) {
              tools[idx] = { ...tools[idx], result: e.result };
            } else {
              tools.push({ step: e.step, name: e.name, result: e.result });
            }
            return { ...last, tools };
          }),
      },
      controller.signal,
    );
  };

  const send = async () => {
    const message = input.trim();
    if (!message || !session || running) return;
    setInput("");
    setRunning(true);
    setEntries((prev) => [
      ...prev,
      { role: "user", text: message },
      { role: "assistant", text: "", tools: [], notices: [] },
    ]);
    try {
      let result;
      try {
        result = await runTurn(session.id, message);
      } catch (err) {
        // Session expirée : recréation depuis le projet client puis une
        // seule relance du même tour.
        if (err instanceof ApiError && err.code === "agt_session_expired") {
          appendAssistant((last) => ({
            ...last,
            notices: [...last.notices, t.sessionExpiredRecreating],
          }));
          const newId = await recreateSession(session);
          result = await runTurn(newId, message);
        } else {
          throw err;
        }
      }
      const done = result.done ?? {};
      const usage = mapUsage(
        (done.usageSession ?? null) as Parameters<typeof mapUsage>[0],
      );
      if (usage) setUsageSession(usage);
      // Coût € indicatif cumulé — absent pour un modèle local.
      const cost = (done as { costSessionEur?: number | null }).costSessionEur;
      if (typeof cost === "number") setCostSession(cost);
    } catch (err) {
      appendAssistant((last) => ({ ...last, error: formatApiError(err) }));
    } finally {
      abortRef.current = null;
      setRunning(false);
    }
  };

  const stop = () => abortRef.current?.abort();

  // Copie le fil au presse-papiers en texte simple (rôles + texte ;
  // les appels d'outils, purement techniques, restent hors du transcript).
  const copyConversation = async () => {
    const transcript = entries
      .map((entry) =>
        entry.role === "user"
          ? `## ${t.you}\n${entry.text}`
          : `## ${t.assistant}\n${entry.text}`,
      )
      .join("\n\n")
      .trim();
    if (!transcript) return;
    try {
      await navigator.clipboard.writeText(transcript);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Échec de copie presse-papiers ignoré (best-effort).
    }
  };

  // Réinitialise la conversation : vide l'historique serveur ET le fil affiché
  // sans détruire la session (le CSV reste chargé). L'agent repart sans
  // mémoire des tours passés.
  const resetConversation = async () => {
    if (!session || running || recreating) return;
    try {
      await resetAgentConversation(session.id);
    } catch {
      // Best-effort : une session expirée sera recréée au prochain tour, déjà
      // sans historique — on vide le fil affiché dans tous les cas.
    }
    setEntries([]);
    // Les compteurs de tokens/coût restent : ils sont cumulés « sur la session »
    // (dépense réelle, conservée côté serveur), pas sur la seule conversation.
  };

  // Widget de chat flottant, ancré bas-droite (pas de modale plein écran) :
  // le reste de l'application reste visible et interactif pendant que
  // l'agent tourne (`modal={false}`, pas d'overlay, clics extérieurs
  // ignorés — seuls Échap et la croix ferment le panneau).
  // Hauteur plafonnée (et non tirée du haut de l'écran) : le panneau se
  // comporte comme une bulle de chat classique plutôt qu'un panneau latéral
  // plein écran.
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange} modal={false}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Content
          onPointerDownOutside={(e) => e.preventDefault()}
          onInteractOutside={(e) => e.preventDefault()}
          className="fixed right-6 bottom-6 z-50 flex h-[min(680px,calc(100vh-3rem))] w-96 max-w-[calc(100vw-3rem)] flex-col gap-0 overflow-hidden rounded-2xl border border-(--ink-200) bg-popover shadow-2xl outline-none data-open:animate-in data-open:slide-in-from-right-4 data-open:slide-in-from-bottom-4 data-open:fade-in-0 data-closed:animate-out data-closed:slide-out-to-right-4 data-closed:slide-out-to-bottom-4 data-closed:fade-out-0"
        >
          <DialogTitle className="sr-only">{t.title}</DialogTitle>
          <DialogDescription className="sr-only">{t.subtitle}</DialogDescription>

          {/* En-tête compact type chatbot : titre + actions sur une seule
              ligne, la croix de fermeture y est intégrée au lieu de flotter
              par-dessus le contenu. */}
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-(--ink-100) px-4 py-3">
            <h2 className="truncate font-heading text-sm font-semibold text-(--ink-900)">
              {t.title}
            </h2>
            <div className="flex shrink-0 items-center gap-1">
              <DialogPrimitive.Close
                aria-label={t.close}
                title={t.close}
                className="inline-flex h-7 w-7 items-center justify-center rounded-md text-(--ink-500) transition hover:bg-(--paper-100) hover:text-(--ink-900) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--graphite-600)"
              >
                <X className="h-4 w-4" />
              </DialogPrimitive.Close>
            </div>
          </div>

          <div className="flex min-h-0 flex-1 flex-col px-4 py-3">
          {DEMO_MODE ? (
            <Alert>
              <AlertDescription>{t.demoDisabled}</AlertDescription>
            </Alert>
          ) : !session ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t.startTitle}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {creating ? (
                  <p className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t.creating}
                  </p>
                ) : createError ? (
                  <>
                    <Alert variant="destructive">
                      <AlertTitle>{t.errorTitle}</AlertTitle>
                      <AlertDescription className="whitespace-pre-line">
                        {createError}
                      </AlertDescription>
                    </Alert>
                    <Button onClick={startFromProject} className="w-full">
                      <RotateCcw className="h-3.5 w-3.5" />
                      {t.retry}
                    </Button>
                  </>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {t.noProjectCsv}
                  </p>
                )}
              </CardContent>
            </Card>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-(--ink-200)">
              <div className="flex shrink-0 items-start justify-between gap-2 border-b border-(--ink-100) px-3 py-1.5 text-[11px] leading-tight text-muted-foreground">
                <div>
                  <p>{t.sessionInfo(session.rows, Math.round(session.ttlS / 60))}</p>
                  {(usageSession?.totalTokens != null || costSession != null) && (
                    <p>
                      {usageSession?.totalTokens != null &&
                        t.usageSession(formatTokens(usageSession.totalTokens))}
                      {usageSession?.totalTokens != null && costSession != null && " · "}
                      {costSession != null && t.costSession(formatCostEur(costSession))}
                    </p>
                  )}
                  {/* Toggle « rapport d'audit en contexte » (0.6.0) : visible
                      seulement si le projet a un rapport. Le basculer recrée la
                      session (contexte figé à la création) → le fil repart. */}
                  {hasAuditReport && (
                    <label
                      className="mt-1 flex w-fit cursor-pointer items-center gap-1.5"
                      title={t.useAuditReportHint}
                    >
                      <input
                        type="checkbox"
                        checked={agentUseAuditReport}
                        onChange={(e) => setAgentUseAuditReport(e.target.checked)}
                        disabled={running || recreating}
                        className="h-3 w-3 shrink-0 accent-(--ink-900) disabled:cursor-not-allowed disabled:opacity-50"
                      />
                      <span>
                        {session.auditReportUsed
                          ? t.auditReportActive
                          : t.useAuditReport}
                      </span>
                    </label>
                  )}
                </div>
                {entries.length > 0 && (
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      onClick={() => void resetConversation()}
                      disabled={running || recreating}
                      title={t.resetConversation}
                      aria-label={t.resetConversation}
                      className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded border border-(--ink-100) bg-(--paper-50) text-(--ink-500) transition hover:bg-(--paper-100) hover:text-(--ink-900) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--graphite-600) disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <RotateCcw className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      onClick={() => void copyConversation()}
                      title={copied ? t.conversationCopied : t.copyConversation}
                      aria-label={copied ? t.conversationCopied : t.copyConversation}
                      className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded border border-(--ink-100) bg-(--paper-50) text-(--ink-500) transition hover:bg-(--paper-100) hover:text-(--ink-900) focus:outline-none focus-visible:ring-2 focus-visible:ring-(--graphite-600)"
                    >
                      {copied ? (
                        <Check className="h-3 w-3 text-(--success-700)" />
                      ) : (
                        <Copy className="h-3 w-3" />
                      )}
                    </button>
                  </div>
                )}
              </div>

              <div
                ref={scrollRef}
                className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3"
              >
                {entries.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    {t.emptyChat}
                  </p>
                )}
                {entries.map((entry, i) =>
                  entry.role === "user" ? (
                    <div key={i} className="flex justify-end">
                      <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-(--ink-900) px-3 py-2 text-sm whitespace-pre-wrap text-(--paper-50)">
                        {entry.text}
                      </div>
                    </div>
                  ) : (
                    <div key={i} className="flex justify-start">
                      <div className="max-w-[85%] space-y-2 rounded-2xl rounded-bl-sm bg-(--paper-100) px-3 py-2">
                        {entry.tools.map((tool, ti) => (
                          <details
                            key={`${tool.step}-${tool.name}-${ti}`}
                            className="rounded-md border border-(--ink-200) bg-(--popover) px-2 py-1.5 text-xs"
                          >
                            <summary className="flex cursor-pointer items-center gap-2 font-medium">
                              <Wrench className="h-3 w-3 shrink-0" />
                              {t.toolCall(tool.name)}
                              {tool.result === undefined && (
                                <Loader2 className="h-3 w-3 animate-spin" />
                              )}
                            </summary>
                            <div className="mt-2 space-y-2">
                              {tool.arguments !== undefined && (
                                <div>
                                  <p className="font-medium text-muted-foreground">
                                    {t.toolArguments}
                                  </p>
                                  <pre className="mt-1 overflow-x-auto rounded bg-(--paper-100) p-2">
                                    {JSON.stringify(tool.arguments, null, 2)}
                                  </pre>
                                </div>
                              )}
                              {tool.result !== undefined && (
                                <div>
                                  <p className="font-medium text-muted-foreground">
                                    {t.toolResult}
                                  </p>
                                  <pre className="mt-1 overflow-x-auto rounded bg-(--paper-100) p-2">
                                    {JSON.stringify(tool.result, null, 2)}
                                  </pre>
                                </div>
                              )}
                            </div>
                          </details>
                        ))}
                        {entry.notices.map((n, j) => (
                          <p key={j} className="text-xs text-muted-foreground">
                            {n}
                          </p>
                        ))}
                        {entry.text ? (
                          <div className="text-sm">
                            <StreamingMarkdown text={entry.text} />
                          </div>
                        ) : (
                          !entry.error &&
                          running &&
                          i === entries.length - 1 && (
                            <p className="flex items-center gap-2 text-sm text-muted-foreground">
                              <Loader2 className="h-4 w-4 animate-spin" />
                              {t.thinking}
                            </p>
                          )
                        )}
                        {entry.error && (
                          <Alert variant="destructive">
                            <AlertTitle>{t.errorTitle}</AlertTitle>
                            <AlertDescription className="whitespace-pre-line">
                              {entry.error}
                            </AlertDescription>
                          </Alert>
                        )}
                      </div>
                    </div>
                  ),
                )}
              </div>

              <div className="flex shrink-0 items-end gap-2 border-t border-(--ink-100) p-2.5">
                <Textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                  placeholder={t.inputPlaceholder}
                  rows={1}
                  className="min-h-9 flex-1 resize-none py-2"
                  disabled={running || recreating}
                />
                {running ? (
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={stop}
                    title={t.stop}
                    aria-label={t.stop}
                  >
                    <Square className="h-3.5 w-3.5" />
                  </Button>
                ) : (
                  <Button
                    size="icon"
                    onClick={() => void send()}
                    disabled={!input.trim() || recreating}
                    title={t.send}
                    aria-label={t.send}
                  >
                    <Send className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            </div>
          )}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}