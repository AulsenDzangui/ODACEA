"use client";

import type {
  SedaRow,
  ResipResult,
  LlmClassementRow,
  ClassementBatch,
  ClassementDirective,
} from "@/lib/csv/types";
import type { LlmUsage } from "@/lib/llm/client-stream";
import type { PlanOrigin, WizardStep } from "@/lib/store";
import { computeProjectMetrics, type ProjectMetrics } from "@/lib/fonds-stats";

const INDEX_KEY = "odacea-projects/index";
const PROJECT_PREFIX = "odacea-projects/";
const LLM_CONFIG_KEY = "odacea-llm-config";

export type StoredProjectIndexEntry = {
  stem: string;
  name: string;
  savedAt: number;
  csvFilename: string;
  /** Mesures compactes du projet — volumes/conformité/durées dérivées de
   *  l'instantané à l'enregistrement, pour bâtir le tableau de bord sans
   *  recharger les CSV. Absente des projets enregistrés avant l'ajout des mesures (recalculée à
   *  la demande par `listProjectMetrics`). */
  metrics?: ProjectMetrics;
};

export type StoredProject = {
  name: string;
  stem: string;
  savedAt: number;

  csvFilename: string;
  csvOriginal: SedaRow[] | null;
  // Racine locale du vrac — chemin sur la machine de l'archiviste, mémorisé
  // pour pré-remplir import direct/enrich/application. Optionnel (absent des projets
  // antérieurs). Aucune donnée documentaire, juste un chemin.
  sourceRoot?: string;

  archivisteObservation: string;

  step: WizardStep;
  rapportAudit: string;
  thinkingAudit: string;
  planValide: string;
  planValideOriginal: string;
  planNotes: string;
  planModifie: boolean;
  // Origine du plan retenu : "audit_llm" ou "fourni". Optionnel : absent des
  // projets enregistrés avant le (→ déduit du plan à la relecture).
  planOrigin?: PlanOrigin;
  // Consignes de classement — optionnel (absent des projets antérieurs → []).
  classementDirectives?: ClassementDirective[];
  briefMode: boolean;
  // Plan de classement de référence retenu pour l'audit. Optionnels :
  // absents des projets enregistrés avant cette version.
  referencePlan?: string;
  referencePlanName?: string;
  referenceMode?: string;

  thinkingClassement: string;
  llmRawResponse: string;
  llmRawRows: LlmClassementRow[] | null;
  classementBatches: ClassementBatch[] | null;
  csvFinal: ResipResult | null;

  lastError: string;

  // Mesures réelles du dernier traitement de ce projet (tokens + durée par
  // agent). Optionnelles : un serveur local n'expose pas toujours les tokens,
  // et les projets enregistrés avant cette version n'en ont pas. Restaurées
  // pour survivre à la réouverture — cf. `applyProjectSnapshot`.
  usageAudit?: LlmUsage | null;
  usageClassementTotal?: LlmUsage | null;
  durationAudit?: number | null;
  durationClassementTotal?: number | null;
  // Version du prompt utilisé par agent — consignée pour interpréter le
  // projet après une évolution des prompts. Absente des projets antérieurs.
  promptVersionAudit?: string | null;
  promptVersionClassement?: string | null;
  // Modèle réellement utilisé par agent — figé à l'exécution, pour savoir quel
  // modèle a produit l'audit / le classement après rechargement. Absent des
  // projets antérieurs.
  modelAudit?: string | null;
  modelClassement?: string | null;
};

export type ProjectSnapshot = Omit<StoredProject, "name" | "stem" | "savedAt">;

export function safeName(name: string): string {
  let n = name.trim();
  n = n.replace(/[^\w\-. ]/gu, "_");
  n = n.replace(/\s+/g, "_");
  n = n.replace(/_+/g, "_").replace(/^_+|_+$/g, "");
  return n || "projet";
}

function readIndex(): StoredProjectIndexEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(INDEX_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as StoredProjectIndexEntry[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeIndex(entries: StoredProjectIndexEntry[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(INDEX_KEY, JSON.stringify(entries));
}

export function listProjects(): StoredProjectIndexEntry[] {
  return readIndex().sort((a, b) => b.savedAt - a.savedAt);
}

export type ProjectMetricsEntry = {
  entry: StoredProjectIndexEntry;
  metrics: ProjectMetrics | null;
};

/**
 * Liste les projets avec leurs mesures (tableau de bord local). Les projets
 * enregistrés depuis portent déjà leurs mesures dans l'index (lecture
 * directe) ; les plus anciens sont recalculés une fois en rechargeant le projet
 * (rétro-compatibilité, sans réécrire l'index). `metrics: null` si le projet est
 * introuvable ou illisible — l'entrée reste listée.
 */
export function listProjectMetrics(): ProjectMetricsEntry[] {
  return listProjects().map((entry) => {
    if (entry.metrics) return { entry, metrics: entry.metrics };
    try {
      const proj = loadProject(entry.stem);
      const { name: _n, stem: _s, savedAt: _d, ...snapshot } = proj;
      return { entry, metrics: computeProjectMetrics(snapshot as ProjectSnapshot) };
    } catch {
      return { entry, metrics: null };
    }
  });
}

/**
 * Renvoie un nom de projet dont le `stem` n'entre pas en collision avec un
 * projet existant. Comme le `stem` (clé de stockage) dérive du nom, deux projets
 * homonymes s'écraseraient ; on suffixe donc « (2) », « (3) »… jusqu'à trouver
 * un stem libre. Sert à nommer les projets auto-créés depuis un même CSV.
 */
export function uniqueProjectName(base: string): string {
  const taken = new Set(readIndex().map((e) => e.stem));
  let name = base;
  let n = 2;
  while (taken.has(safeName(name))) {
    name = `${base} (${n})`;
    n += 1;
  }
  return name;
}

export function saveProject(
  name: string,
  snapshot: ProjectSnapshot,
  explicitStem?: string,
): string {
  if (typeof window === "undefined") {
    throw new Error("saveProject doit être appelé côté client.");
  }
  const stem = explicitStem ?? safeName(name);
  if (!stem) {
    throw new Error("Le nom du projet ne peut pas être vide.");
  }
  const savedAt = Date.now();
  const stored: StoredProject = {
    name: name.trim() || stem.replace(/_/g, " "),
    stem,
    savedAt,
    ...snapshot,
  };
  window.localStorage.setItem(
    PROJECT_PREFIX + stem,
    JSON.stringify(stored),
  );
  const index = readIndex().filter((e) => e.stem !== stem);
  index.push({
    stem,
    name: stored.name,
    savedAt,
    csvFilename: snapshot.csvFilename,
    metrics: computeProjectMetrics(snapshot),
  });
  writeIndex(index);
  return stem;
}

export function loadProject(stem: string): StoredProject {
  if (typeof window === "undefined") {
    throw new Error("loadProject doit être appelé côté client.");
  }
  const raw = window.localStorage.getItem(PROJECT_PREFIX + stem);
  if (!raw) {
    throw new Error(`Projet introuvable : ${stem}`);
  }
  return JSON.parse(raw) as StoredProject;
}

/**
 * Renomme un projet et recalcule son `stem` depuis le nouveau nom.
 * Si le stem change, migre les données vers la nouvelle clé localStorage et
 * met à jour l'index. Retourne le stem effectif après renommage.
 */
export function renameProject(stem: string, newName: string): string {
  if (typeof window === "undefined") return stem;
  const trimmed = newName.trim();
  if (!trimmed) {
    throw new Error("Le nom du projet ne peut pas être vide.");
  }
  const newStem = safeName(trimmed);

  if (newStem !== stem) {
    const taken = new Set(readIndex().map((e) => e.stem));
    if (taken.has(newStem)) {
      throw new Error("Un projet avec ce nom existe déjà.");
    }
    const raw = window.localStorage.getItem(PROJECT_PREFIX + stem);
    if (raw) {
      const stored = JSON.parse(raw) as StoredProject;
      stored.name = trimmed;
      stored.stem = newStem;
      window.localStorage.setItem(PROJECT_PREFIX + newStem, JSON.stringify(stored));
      window.localStorage.removeItem(PROJECT_PREFIX + stem);
    }
    writeIndex(
      readIndex().map((e) =>
        e.stem === stem ? { ...e, stem: newStem, name: trimmed } : e,
      ),
    );
  } else {
    const raw = window.localStorage.getItem(PROJECT_PREFIX + stem);
    if (raw) {
      const stored = JSON.parse(raw) as StoredProject;
      stored.name = trimmed;
      window.localStorage.setItem(PROJECT_PREFIX + stem, JSON.stringify(stored));
    }
    writeIndex(
      readIndex().map((e) => (e.stem === stem ? { ...e, name: trimmed } : e)),
    );
  }

  return newStem;
}

export function deleteProject(stem: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(PROJECT_PREFIX + stem);
  writeIndex(readIndex().filter((e) => e.stem !== stem));
}

export function duplicateProject(stem: string): string {
  const proj = loadProject(stem);
  const baseName = `${proj.name} (copie)`;
  const newName = uniqueProjectName(baseName);
  const { name: _n, stem: _s, savedAt: _d, ...snapshot } = proj;
  return saveProject(newName, snapshot);
}

// ── Quota localStorage (D9) ──────────────────────────────────────────────────
// localStorage n'expose pas son quota ; la limite usuelle des navigateurs est
// ~5 Mo par origine. On mesure l'occupation réelle (somme des paires clé/valeur,
// ×2 pour l'encodage UTF-16) et on prévient avant la saturation — un projet avec
// gros CSV + CSV final peut peser plusieurs centaines de Ko.
export const LOCALSTORAGE_BUDGET_BYTES = 5 * 1024 * 1024;
/** Seuil d'alerte : 80 % du budget estimé. */
export const LOCALSTORAGE_WARN_RATIO = 0.8;

export type StorageUsage = { bytes: number; ratio: number };

export function estimateStorageUsage(): StorageUsage {
  if (typeof window === "undefined") return { bytes: 0, ratio: 0 };
  let bytes = 0;
  try {
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (key === null) continue;
      const value = window.localStorage.getItem(key) ?? "";
      bytes += (key.length + value.length) * 2;
    }
  } catch {
    return { bytes: 0, ratio: 0 };
  }
  return { bytes, ratio: bytes / LOCALSTORAGE_BUDGET_BYTES };
}

// ── Export / import de projet (.json) (D9) ───────────────────────────────────
// Portabilité d'un projet entre postes : fichier autonome (aucun secret — la
// config LLM/clé API vit dans une clé séparée, non incluse).

const EXPORT_FORMAT = "odacea-project";
const EXPORT_VERSION = 1;

type ExportEnvelope = {
  format: typeof EXPORT_FORMAT;
  version: number;
  exportedAt: number;
  project: StoredProject;
};

/** Sérialise un projet stocké en JSON autonome (téléchargeable). */
export function exportProjectJson(stem: string): { filename: string; json: string } {
  const project = loadProject(stem);
  const envelope: ExportEnvelope = {
    format: EXPORT_FORMAT,
    version: EXPORT_VERSION,
    exportedAt: Date.now(),
    project,
  };
  return {
    filename: `${project.stem}.odacea.json`,
    json: JSON.stringify(envelope, null, 2),
  };
}

/**
 * Importe un projet depuis le JSON d'un fichier exporté. Valide l'enveloppe,
 * attribue un nom/stem libre (jamais d'écrasement d'un projet existant) et
 * persiste. Retourne `{ stem, name }` du projet importé.
 */
export function importProjectJson(raw: string): { stem: string; name: string } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("Fichier illisible : JSON invalide.");
  }
  const env = parsed as Partial<ExportEnvelope>;
  if (!env || env.format !== EXPORT_FORMAT || !env.project) {
    throw new Error("Ce fichier n'est pas un projet ODACEA exporté.");
  }
  if (typeof env.version === "number" && env.version > EXPORT_VERSION) {
    throw new Error(
      "Ce projet a été exporté par une version plus récente d'ODACEA.",
    );
  }
  const project = env.project;
  const { name: _n, stem: _s, savedAt: _d, ...snapshot } = project;
  const name = uniqueProjectName(project.name || "Projet importé");
  const stem = saveProject(name, snapshot as ProjectSnapshot);
  return { stem, name };
}

// ── Configuration LLM (modèle / serveur / clé API) ─────────────────────────
// Persistée indépendamment des projets, pour survivre d'une session à l'autre.
// N'inclut volontairement pas les optimisations de tokens.

export type StoredLlmConfig = {
  providerMode?: "cloud" | "local";
  cloudModel?: string;
  apiKey?: string;
  /** Mémorisation explicite de la clé API. `false` (défaut) = la clé n'est
   *  jamais écrite dans `localStorage` (session-only : conservée en mémoire pour
   *  la session courante, oubliée au rechargement). `true` = opt-in, la clé est
   *  persistée en clair sur cet appareil. La préférence, elle, est toujours
   *  persistée. */
  rememberApiKey?: boolean;
  localEndpoint?: string;
  localModel?: string;
};

export function loadLlmConfig(): StoredLlmConfig | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LLM_CONFIG_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredLlmConfig;
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export function saveLlmConfig(config: StoredLlmConfig): void {
  if (typeof window === "undefined") return;
  try {
    // Garde de confidentialité appliquée à la frontière du stockage : tant
    // que la mémorisation n'est pas explicitement activée, la clé API n'est
    // jamais sérialisée sur disque, quel que soit l'appelant.
    const toStore: StoredLlmConfig = config.rememberApiKey
      ? config
      : { ...config, apiKey: undefined };
    window.localStorage.setItem(LLM_CONFIG_KEY, JSON.stringify(toStore));
  } catch {
    /* quota / navigation privée — on ignore */
  }
}

// ── Préférences d'affichage ────────────────────────────────────────────────
// Choix d'interface qui suivent les habitudes de l'utilisateur d'une session à
// l'autre, indépendamment des projets (ex. type de titre des dossiers à l'export).

const UI_PREFS_KEY = "odacea-ui-prefs";

export type StoredUiPrefs = {
  /** Titre des dossiers à l'export : true = nom technique (champ File). */
  folderTitleFromFile?: boolean;
  /** Titre des fichiers à l'export : true = titre d'origine importé (le
   *  renommage produit par l'IA est ignoré). */
  keepOriginalFileTitle?: boolean;
  /** Retirer le préfixe de position des noms de dossier à l'export (colonne
   *  File) : true = `1-1_Lettres` → `Lettres`. Appliqué au finalize côté moteur
   *  (une bascule re-finalise). Conservé comme une habitude. */
  stripFolderNumbers?: boolean;
  /** Demander l'« avis de classement » au classement (option d'optimisation
   *  CLA-001). Conservée comme une habitude, indépendamment des projets. */
  classementAvis?: boolean;
  /** Méthode d'identifiant « Ref » (identifiant court) au classement. Conservée
   *  comme une habitude, indépendamment des projets. */
  classementRef?: boolean;
  /** Nombre d'items par lot au classement (découpage CLA-001). Réglage de
   *  traitement conservé entre sessions ; borné à la relecture. */
  classementBatchSize?: number;
  /** Lots CLA-001 traités en parallèle. Réglage conservé entre sessions ;
   *  borné à la relecture. La garde « forcé séquentiel en local » reste appliquée
   *  au lancement (jamais depuis le stockage). */
  classementConcurrency?: number;
  /** Donner le rapport d'audit du projet en contexte à l'agent (0.6.0). Réglage
   *  conservé entre sessions ; ON par défaut (n'a d'effet que si un rapport
   *  existe). Changer ce réglage recrée la session de l'agent. */
  agentUseAuditReport?: boolean;
};

export function loadUiPrefs(): StoredUiPrefs | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(UI_PREFS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredUiPrefs;
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export function saveUiPrefs(prefs: StoredUiPrefs): void {
  if (typeof window === "undefined") return;
  try {
    const current = loadUiPrefs() ?? {};
    window.localStorage.setItem(
      UI_PREFS_KEY,
      JSON.stringify({ ...current, ...prefs }),
    );
  } catch {
    /* quota / navigation privée — on ignore */
  }
}
