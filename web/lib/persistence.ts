"use client";

import type {
  SedaRow,
  ResipResult,
  LlmClassementRow,
  ClassementBatch,
  ClassementDirective,
} from "@/lib/csv/types";
import type { WizardStep } from "@/lib/store";

const INDEX_KEY = "odacea-projects/index";
const PROJECT_PREFIX = "odacea-projects/";
const LLM_CONFIG_KEY = "odacea-llm-config";

export type StoredProjectIndexEntry = {
  stem: string;
  name: string;
  savedAt: number;
  csvFilename: string;
};

export type StoredProject = {
  name: string;
  stem: string;
  savedAt: number;

  csvFilename: string;
  csvOriginal: SedaRow[] | null;

  archivisteObservation: string;

  step: WizardStep;
  rapportAudit: string;
  thinkingAudit: string;
  planValide: string;
  planValideOriginal: string;
  planNotes: string;
  planModifie: boolean;
  briefMode: boolean;

  thinkingClassement: string;
  llmRawResponse: string;
  llmRawRows: LlmClassementRow[] | null;
  classementBatches: ClassementBatch[] | null;
  /** Consignes de classement de l'archiviste — optionnel : absent des projets
   *  enregistrés avant leur introduction. */
  classementDirectives?: ClassementDirective[];
  csvFinal: ResipResult | null;

  lastError: string;
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

// ── Configuration LLM (modèle / serveur / clé API) ─────────────────────────
// Persistée indépendamment des projets, pour survivre d'une session à l'autre.
// N'inclut volontairement pas les optimisations de tokens.

export type StoredLlmConfig = {
  providerMode?: "cloud" | "local";
  cloudModel?: string;
  apiKey?: string;
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
    window.localStorage.setItem(LLM_CONFIG_KEY, JSON.stringify(config));
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
