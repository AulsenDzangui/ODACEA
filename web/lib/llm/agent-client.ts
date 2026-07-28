// Client transport des endpoints /agt/* (agent conversationnel
// **lecture seule** d'exploration de vrac). Transport pur : les types
// ci-dessous décalquent les charges utiles construites côté moteur
// (backend/api/engine.py, agt_*) — le front les affiche et les renvoie telles
// quelles, aucune logique métier en TS.
//
// Le tour de chat (`POST /agt/chat`, SSE) passe par `streamSse` directement
// (événements `tool`/`toolResult` via `StreamCallbacks.onTool`).

import { postJson, ApiError } from "@/lib/llm/client-stream";

export type AgentSessionCreated = {
  sessionId: string;
  stats: Record<string, unknown>;
  digest: string;
  ttlS: number;
  /** Le rapport d'audit du projet a-t-il été injecté en contexte (0.6.0) ?
   *  Reflète ce que le backend a réellement retenu (rapport vide ⇒ false). */
  auditReportUsed?: boolean;
};

/** Charge utile `done{}` du tour de chat (`/agt/chat`). */
export type AgentChatDone = {
  answer?: string;
  steps?: number;
  usageSession?: {
    input_tokens?: number | null;
    output_tokens?: number | null;
    total_tokens?: number | null;
  } | null;
  /** Coût € indicatif cumulé de la session — absent/null pour un modèle
   * local ou cloud hors grille (rien à afficher). */
  costSessionEur?: number | null;
  toolMode?: string;
  durationMs?: number;
  promptVersion?: string;
  model?: string;
};

export async function createAgentSession(
  params: { csv: string; auditReport?: string },
  signal?: AbortSignal,
): Promise<AgentSessionCreated> {
  return postJson<AgentSessionCreated>(
    "/agt/session",
    // `auditReport` optionnel (0.6.0) : rapport d'audit du projet en contexte de
    // l'agent. Omis quand vide/désactivé ⇒ le backend garde le prompt inchangé.
    { csv: params.csv, auditReport: params.auditReport || undefined },
    signal,
  );
}

export async function deleteAgentSession(sessionId: string): Promise<void> {
  await fetch(`/api/py/agt/session/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    // Suppression best-effort (départ de page) : une session expirée ou un
    // backend éteint ne doivent pas produire d'erreur visible.
    keepalive: true,
  }).catch(() => {});
}

/** Réinitialise la conversation en cours : vide l'historique de dialogue
 *  côté serveur **sans détruire la session**. L'agent repart sans mémoire des
 *  tours précédents. */
export async function resetAgentConversation(
  sessionId: string,
): Promise<{ reset: boolean }> {
  const res = await fetch(
    `/api/py/agt/session/${encodeURIComponent(sessionId)}/history`,
    { method: "DELETE" },
  );
  const data = (await res.json()) as {
    reset?: boolean;
    error?: string;
    code?: string;
    hint?: string;
  };
  if (!res.ok || data.error) {
    throw new ApiError(data.error || `HTTP ${res.status}`, data.code, data.hint);
  }
  return { reset: data.reset ?? false };
}
