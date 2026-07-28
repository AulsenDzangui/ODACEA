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

/** Inverse de `mapUsage` : ré-aplatit un `LlmUsage` (camelCase) vers la forme
 *  normalisée snake_case que le backend attend (ex. `core.tokens.format_usage_line`,
 *  consommé par `/journal`). Transport pur — aucune logique métier ; les clés à
 *  `undefined` sont omises pour ne pas faire passer de zéro factice. */
export function unmapUsage(
  u: LlmUsage | null | undefined,
): Record<string, number> | null {
  if (!u) return null;
  const out: Record<string, number> = {};
  const put = (k: string, v: number | undefined) => {
    if (typeof v === "number") out[k] = v;
  };
  put("input_tokens", u.inputTokens);
  put("output_tokens", u.outputTokens);
  put("total_tokens", u.totalTokens);
  put("cache_read_tokens", u.inputDetails?.cacheReadTokens);
  put("reasoning_tokens", u.outputDetails?.reasoningTokens);
  return out;
}

/** Erreur structurée renvoyée par le backend (taxonomie) : `code` est un
 *  identifiant stable, `hint` l'action recommandée — affichée à l'utilisateur
 *  pour rendre l'erreur exploitable sans ouvrir la console. */
export class ApiError extends Error {
  code?: string;
  hint?: string;
  constructor(message: string, code?: string, hint?: string) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.hint = hint;
  }
}

/** Message d'erreur prêt à afficher : message + hint sur une seconde ligne
 *  (les conteneurs d'alerte utilisent `whitespace-pre-line`). */
export function formatApiError(err: unknown): string {
  if (err instanceof ApiError && err.hint) return `${err.message}\n→ ${err.hint}`;
  return err instanceof Error ? err.message : String(err);
}

type ErrorPayload = { error?: string; code?: string; hint?: string };

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
  const payload = (data ?? {}) as ErrorPayload;
  if (!res.ok || payload.error) {
    throw new ApiError(
      payload.error || `HTTP ${res.status}`,
      payload.code,
      payload.hint,
    );
  }
  return data as T;
}

export async function putJson<T = unknown>(
  endpoint: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const data = await res.json();
  const payload = (data ?? {}) as ErrorPayload;
  if (!res.ok || payload.error) {
    throw new ApiError(
      payload.error || `HTTP ${res.status}`,
      payload.code,
      payload.hint,
    );
  }
  return data as T;
}

export async function getJson<T = unknown>(
  endpoint: string,
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    method: "GET",
    signal,
  });
  const data = await res.json();
  const payload = (data ?? {}) as ErrorPayload;
  if (!res.ok || payload.error) {
    throw new ApiError(
      payload.error || `HTTP ${res.status}`,
      payload.code,
      payload.hint,
    );
  }
  return data as T;
}

/** Réponse de `POST /reference-plan/from-csv` : conversion d'un CSV Resip
 *  « dossiers seuls » en bloc arborescence injectable comme plan de référence.
 * Le `tree` et l'injection comme contrainte d'audit restent côté moteur ;
 *  le front ne transporte que le bloc et l'affiche. */
export type ReferencePlanFromCsv = {
  tree: string;
  validationErrors: string[];
  warnings: string[];
  folderCount: number;
  ignoredItemCount: number;
  rootTitle: string;
};

/** Convertit un CSV Resip « dossiers seuls » en plan de classement de référence
 *. Mêmes contrôles que l'upload de départ ; les erreurs de transport
 *  (413/400/502) remontent en `ApiError` (gérées par l'appelant). */
export async function referencePlanFromCsv(
  csv: string,
  signal?: AbortSignal,
): Promise<ReferencePlanFromCsv> {
  return postJson<ReferencePlanFromCsv>(
    "/reference-plan/from-csv",
    { csv },
    signal,
  );
}

// ── — souveraineté de l'archiviste sur le plan ───────────────────────────────
// Transport pur : la conversion, la matérialisation, le scan et l'aperçu des
// changements vivent dans le moteur Python (`core/plan_folders.py`). Le front ne
// fait qu'envoyer un texte/chemin et présenter le résultat.

/** Réponse de `POST /plan/from-file` : plan fourni par l'archiviste adopté
 *  **sans appel LLM** (CSV Resip « dossiers seuls » ou Markdown canonique). */
export type PlanFromFile = {
  plan: string;
  planTree: Record<string, string | null>;
  folderCount: number;
  ignoredItemCount: number;
  rootTitle: string;
  warnings: string[];
  format: "csv" | "markdown";
};

/** Adopte un plan fourni par l'archiviste — bypass de l'audit LLM. */
export async function planFromFile(
  name: string,
  content: string,
  signal?: AbortSignal,
): Promise<PlanFromFile> {
  return postJson<PlanFromFile>("/plan/from-file", { name, content }, signal);
}

/** Réponse de `POST /plan/materialize` — dossiers vides écrits sous workDir. */
export type PlanMaterialize = {
  folderCount: number;
  workDir: string;
  cleared: boolean;
};

/** Matérialise le plan courant en dossiers vides réels (backend local). */
export async function planMaterialize(
  planValide: string,
  workDir: string,
  opts: { clear?: boolean; confirm?: boolean } = {},
  signal?: AbortSignal,
): Promise<PlanMaterialize> {
  return postJson<PlanMaterialize>(
    "/plan/materialize",
    { planValide, workDir, clear: !!opts.clear, confirm: !!opts.confirm },
    signal,
  );
}

/** Aperçu des changements entre le plan courant et le répertoire re-scanné. */
export type PlanChanges = {
  added: string[];
  removed: string[];
  renamed: { from: string; to: string }[];
  moved: { from: string; to: string }[];
  unchanged: number;
  identical: boolean;
};

/** Réponse de `POST /plan/from-folder` : plan canonique reconstruit + aperçu. */
export type PlanFromFolder = {
  plan: string;
  planTree: Record<string, string | null>;
  folderCount: number;
  ignoredFileCount: number;
  rootTitle: string;
  warnings: string[];
  changes?: PlanChanges;
};

/** Re-scanne un répertoire réorganisé dans l'Explorateur et reconstruit le plan
 * canonique (backend local). `currentPlan` alimente l'aperçu des changements. */
export async function planFromFolder(
  workDir: string,
  currentPlan: string,
  signal?: AbortSignal,
): Promise<PlanFromFolder> {
  return postJson<PlanFromFolder>(
    "/plan/from-folder",
    { workDir, currentPlan },
    signal,
  );
}

/** Étape 0 facultative `enrich` — **backend local uniquement**. Le serveur
 *  lit les binaires sous `sourceRoot` (machine de l'archiviste) et renvoie le CSV
 *  enrichi en texte ; le front le réinjecte dans `/parse`. Refusé en démo
 * (`enrich_disabled`, 403). Transport pur : aucune logique métier en TS —
 *  l'extraction, l'empreinte et le rendu vivent dans le moteur Python. */
export type EnrichParams = {
  csv: string;
  /** Racine locale du vrac, accessible depuis la machine qui héberge le backend. */
  sourceRoot: string;
  /** Réécrire une `Content.Description` déjà renseignée. */
  overwrite: boolean;
  /** Calculer aussi l'empreinte SHA-256 (doublons stricts). */
  fingerprint: boolean;
};

/** Compteurs d'extraction de description renvoyés par `/enrich`. */
export type EnrichReport = {
  totalItems: number;
  enriched: number;
  alreadyFilled: number;
  noText: number;
  unsupported: number;
  missing: number;
  errors: number;
};

/** Compteurs d'empreinte SHA-256 renvoyés par `/enrich` (option `fingerprint`). */
export type EnrichFingerprint = {
  totalItems: number;
  hashed: number;
  alreadyHashed: number;
  missing: number;
  skipped: number;
  errors: number;
};

/** Synthèse des groupes binairement identiques (doublons stricts). */
export type EnrichDuplicates = {
  groups: number;
  files: number;
  redundant: number;
  examples: unknown[];
};

/** Réponse de `/enrich` : CSV enrichi (texte) + rapports déterministes. */
export type EnrichResult = {
  enrichedCsv: string;
  contentAccessNotice: string;
  report?: EnrichReport;
  fingerprint?: EnrichFingerprint;
  duplicates?: EnrichDuplicates;
};

/** Exécute l'étape 0 `enrich` via `POST /enrich`. Transport pur — propage les
 * `ApiError` (taxonomie : `enrich_disabled` en démo, `enrich_source_missing`
 *  si le dossier est introuvable). */
export async function enrichCsv(
  params: EnrichParams,
  signal?: AbortSignal,
): Promise<EnrichResult> {
  return postJson<EnrichResult>("/enrich", { ...params }, signal);
}

/** Forme structurelle d'une variante de plan, telle que calculée par le
 * moteur (`core.plan_compare`). Le front n'en fait que l'affichage. */
export type PlanVariantMetrics = {
  index: number;
  planExtracted: boolean;
  folders: number;
  depth: number;
  maxWidth: number;
  leaves: number;
  folderLabels: string[];
  /** Libellés de dossier présents dans cette variante et dans aucune autre. */
  uniqueFolders: string[];
};

/** Croisement global des variantes — dossiers communs/union, amplitudes. */
export type PlanComparison = {
  variantCount: number;
  commonFolders: string[];
  commonFolderCount: number;
  allFolders: string[];
  identical: boolean;
  folderCountRange: { min: number; max: number };
  depthRange: { min: number; max: number };
  leavesRange: { min: number; max: number };
};

/** Réponse de `/plan-compare` : comparaison structurelle + rendu lisible
 *  (tableau récapitulatif rendu par le moteur — source unique). */
export type PlanCompareResult = {
  variants: PlanVariantMetrics[];
  comparison: PlanComparison;
  markdown: string;
};

/** Compare N variantes de plan via `POST /plan-compare`. Transport pur —
 *  toute la comparaison (libellés sémantiques, dossiers communs/propres,
 *  amplitudes) vit dans le moteur Python ; le front ne fait que présenter et
 * laisser l'archiviste choisir une variante (aucune logique métier en TS). */
export async function comparePlans(
  plans: string[],
  signal?: AbortSignal,
): Promise<PlanCompareResult> {
  return postJson<PlanCompareResult>("/plan-compare", { plans }, signal);
}

// ── — prise directe sur le fonds réel (dossier local ↔ arborescence) ──────────
// Transport pur : le scan (métadonnées seules), la dérivation du CSV et la
// copie physique vivent dans le moteur Python (`core/source_scan.py`,
// `core/apply_classement.py`). Le front n'envoie que des chemins et présente le
// résultat. **Backend local uniquement** (refusés en démo).

/** Stats du scan d'un dossier local renvoyées par `/parse/from-folder`. */
export type ScanStats = {
  itemCount: number;
  folderCount: number;
  rootTitle: string;
  excludedCount: number;
  skippedSymlinks: number;
};

/** Importe un **dossier local** : le moteur scanne l'arborescence réelle
 *  (aucun binaire ouvert) et renvoie la même réponse que `/parse` + `derivedCsv`
 *  (téléchargeable) + `scan`. Générique sur la charge `/parse` (le CSV dérivé
 *  repasse par la même porte). Refusé en démo (`parse_local_only`, 403). */
export async function parseFromFolder<T = unknown>(
  params: {
    sourceRoot: string;
    prep: Record<string, unknown>;
    batchSize: number;
    model?: string;
    baseUrl?: string;
  },
  signal?: AbortSignal,
): Promise<T & { derivedCsv: string; scan: ScanStats }> {
  return postJson<T & { derivedCsv: string; scan: ScanStats }>(
    "/parse/from-folder",
    { ...params },
    signal,
  );
}

/** Aperçu de l'application physique du classement renvoyé par
 *  `/apply/preview` — avant toute écriture. */
export type ApplyPreview = {
  total: number;
  copyable: number;
  missing: string[];
  missingCount: number;
  atRoot: string[];
  atRootCount: number;
  renamedCollisions: { wanted: string; resolved: string }[];
  collisionCount: number;
  sanitizedNames: { original: string; sanitized: string }[];
  operations: { sourceRel: string; targetRel: string }[];
  /** Garde-fou du répertoire cible : non-null = refus à lever avant d'écrire. */
  targetGuard: { error: string; code: string; hint: string } | null;
};

/** Aperçu avant écriture : total à copier, collisions, binaires introuvables,
 * items à la racine, et contrôle des garde-fous cible. Aucune copie. */
export async function applyPreview(
  rows: Record<string, unknown>[],
  sourceRoot: string,
  targetRoot: string,
  resume: boolean,
  signal?: AbortSignal,
): Promise<ApplyPreview> {
  return postJson<ApplyPreview>(
    "/apply/preview",
    { rows, sourceRoot, targetRoot, resume },
    signal,
  );
}

/** Statistiques finales de l'application physique, portées par le `done`. */
export type ApplyStats = {
  total: number;
  copied: number;
  skipped: number;
  failed: number;
  errors: { sourceRel: string; error: string }[];
  targetRoot: string;
};

/** Exécute l'application physique du classement en SSE — copie du SIP vers
 *  `targetRoot` (la source n'est jamais mutée). Progression via `onProgress`
 *  (champs `copied`/`total`/`current`), stats finales dans `done.stats`.
 *  `confirm` obligatoire ; `resume` autorise une reprise idempotente. */
export async function applyClassement(
  args: {
    rows: Record<string, unknown>[];
    sourceRoot: string;
    targetRoot: string;
    resume: boolean;
    confirm: boolean;
  },
  callbacks: StreamCallbacks = {},
  signal?: AbortSignal,
): Promise<StreamResult> {
  return streamSse("/apply", { ...args }, callbacks, signal);
}

export type Progress = {
  batch: number;
  totalBatches: number;
  itemsDone: number;
  // Champs de progression de l'application physique du classement —
  // optionnels, absents pour la progression du classement par lots.
  copied?: number;
  skipped?: number;
  failed?: number;
  total?: number;
  current?: string;
};

/** Appel d'outil de l'agent : `call` à l'émission (`tool`),
 *  `result` au retour (`toolResult`). Transparence — le front affiche les
 *  deux tels quels (arguments et résultat opaques, construits côté moteur). */
export type ToolEvent = {
  kind: "call" | "result";
  step: number;
  name: string;
  arguments?: unknown;
  result?: unknown;
};

export type StreamCallbacks = {
  onText?: (delta: string) => void;
  onReasoning?: (delta: string) => void;
  onProgress?: (p: Progress) => void;
  /** Information non bloquante émise par le backend (ex. retry LLM en cours). */
  onNotice?: (message: string) => void;
  /** Appels d'outils de l'agent (`tool` / `toolResult`). */
  onTool?: (e: ToolEvent) => void;
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
  code?: string;
  hint?: string;
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
    let err = new ApiError(`HTTP ${res.status}`);
    try {
      const data = (await res.json()) as ErrorPayload;
      if (data.error) err = new ApiError(data.error, data.code, data.hint);
    } catch {}
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
          case "notice": {
            if (chunk.message) callbacks.onNotice?.(chunk.message);
            break;
          }
          case "tool": {
            callbacks.onTool?.({
              kind: "call",
              step: typeof chunk.step === "number" ? chunk.step : 0,
              name: typeof chunk.name === "string" ? chunk.name : "",
              arguments: chunk.arguments,
            });
            break;
          }
          case "toolResult": {
            callbacks.onTool?.({
              kind: "result",
              step: typeof chunk.step === "number" ? chunk.step : 0,
              name: typeof chunk.name === "string" ? chunk.name : "",
              result: chunk.result,
            });
            break;
          }
          case "progress": {
            const numOrUndef = (v: unknown) =>
              typeof v === "number" ? v : undefined;
            callbacks.onProgress?.({
              batch: chunk.batch ?? 0,
              totalBatches: chunk.totalBatches ?? 0,
              itemsDone: chunk.itemsDone ?? 0,
              // Progression de l'application physique (copie).
              copied: numOrUndef(chunk.copied),
              skipped: numOrUndef(chunk.skipped),
              failed: numOrUndef(chunk.failed),
              total: numOrUndef(chunk.total),
              current: typeof chunk.current === "string" ? chunk.current : undefined,
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
            const err = new ApiError(
              chunk.message ?? "Erreur du flux LLM",
              chunk.code,
              chunk.hint,
            );
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
