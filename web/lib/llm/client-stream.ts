// Client du backend Python (FastAPI), proxifié via /api/py/* (rewrites Next).
// Deux helpers : postJson (endpoints synchrones) et streamSse (endpoints SSE).
//
// Protocole SSE : chaque message est une ligne `data: {json}` avec un champ
// `type` ∈ reasoning | text | progress | done | error.

export const API_BASE = "/api/py";

export type LlmUsage = {
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  inputDetails?: {
    cacheReadTokens?: number;
    cacheWriteTokens?: number;
  };
  outputDetails?: {
    reasoningTokens?: number;
  };
};

/** Usage normalisé renvoyé par le backend Python (snake_case) → LlmUsage. */
type PyUsage = {
  input_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
  cache_read_tokens?: number | null;
  reasoning_tokens?: number | null;
} | null | undefined;

export function mapUsage(u: PyUsage): LlmUsage | null {
  if (!u || typeof u !== "object") return null;
  const num = (v: unknown) => (typeof v === "number" ? v : undefined);
  return {
    inputTokens: num(u.input_tokens),
    outputTokens: num(u.output_tokens),
    totalTokens: num(u.total_tokens),
    inputDetails: { cacheReadTokens: num(u.cache_read_tokens) },
    outputDetails: { reasoningTokens: num(u.reasoning_tokens) },
  };
}

export async function postJson<T = unknown>(
  endpoint: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const data = await res.json();
  if (
    !res.ok ||
    (data && typeof data === "object" && "error" in data && data.error)
  ) {
    const msg =
      (data && typeof data === "object" && "error" in data && (data.error as string)) ||
      `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return data as T;
}

export type Progress = { batch: number; totalBatches: number; itemsDone: number };

export type StreamCallbacks = {
  onText?: (delta: string) => void;
  onReasoning?: (delta: string) => void;
  onProgress?: (p: Progress) => void;
  onError?: (err: Error) => void;
};

export type DonePayload = Record<string, unknown>;

export type StreamResult = {
  text: string;
  reasoning: string;
  usage: LlmUsage | null;
  /** Charge utile complète de l'événement `done` (champs spécifiques à l'endpoint). */
  done: DonePayload | null;
  /** Vrai si le flux a été interrompu par l'utilisateur (AbortSignal). Le texte et
   *  le raisonnement accumulés jusqu'à l'interruption sont alors renvoyés tels quels
   *  (au lieu d'être perdus), pour que l'appelant puisse conserver le travail du modèle. */
  aborted: boolean;
};

type SseChunk = {
  type: string;
  delta?: string;
  message?: string;
  batch?: number;
  totalBatches?: number;
  itemsDone?: number;
  usage?: PyUsage;
  [key: string]: unknown;
};

export async function streamSse(
  endpoint: string,
  body: Record<string, unknown>,
  callbacks: StreamCallbacks = {},
  signal?: AbortSignal,
): Promise<StreamResult> {
  let fullText = "";
  let fullReasoning = "";
  let usage: LlmUsage | null = null;
  let done: DonePayload | null = null;

  // L'interruption (AbortSignal) peut survenir avant même la réponse : on renvoie
  // alors un résultat vide marqué `aborted` plutôt que de propager l'exception.
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      return { text: "", reasoning: "", usage: null, done: null, aborted: true };
    }
    throw err;
  }

  if (!res.ok || !res.body) {
    let errMsg = `HTTP ${res.status}`;
    try {
      const data = (await res.json()) as { error?: string };
      if (data.error) errMsg = data.error;
    } catch {}
    const err = new Error(errMsg);
    callbacks.onError?.(err);
    throw err;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let aborted = false;

  // L'interruption en cours de flux fait rejeter `reader.read()` avec une
  // AbortError : on sort proprement de la boucle en conservant ce qui a déjà été
  // accumulé (fullText/fullReasoning), au lieu de tout perdre via un throw.
  try {
    while (true) {
      const { done: streamDone, value } = await reader.read();
      if (streamDone) break;
      buffer += decoder.decode(value, { stream: true });

      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).replace(/\r$/, "");
        buffer = buffer.slice(nl + 1);
        if (!line || !line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        let chunk: SseChunk;
        try {
          chunk = JSON.parse(payload) as SseChunk;
        } catch {
          continue;
        }

        switch (chunk.type) {
          case "text": {
            const delta = chunk.delta ?? "";
            if (delta) {
              fullText += delta;
              callbacks.onText?.(delta);
            }
            break;
          }
          case "reasoning": {
            const delta = chunk.delta ?? "";
            if (delta) {
              fullReasoning += delta;
              callbacks.onReasoning?.(delta);
            }
            break;
          }
          case "progress": {
            callbacks.onProgress?.({
              batch: chunk.batch ?? 0,
              totalBatches: chunk.totalBatches ?? 0,
              itemsDone: chunk.itemsDone ?? 0,
            });
            break;
          }
          case "done": {
            const { type: _t, ...rest } = chunk;
            void _t;
            done = rest;
            usage = mapUsage(chunk.usage);
            break;
          }
          case "error": {
            const err = new Error(chunk.message ?? "Erreur du flux LLM");
            callbacks.onError?.(err);
            throw err;
          }
          default:
            break;
        }
      }
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      aborted = true;
    } else {
      throw err;
    }
  }

  return { text: fullText, reasoning: fullReasoning, usage, done, aborted };
}
