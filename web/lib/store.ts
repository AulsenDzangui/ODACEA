import { create } from "zustand";
import type {
  SedaRow,
  ResipResult,
  LlmClassementRow,
  ClassementBatch,
} from "@/lib/csv/types";
import type { LlmUsage } from "@/lib/llm/client-stream";
import { DEFAULT_MODEL, LOCAL_MODEL_FALLBACK } from "@/lib/llm/config";
import {
  loadLlmConfig,
  saveLlmConfig,
  loadUiPrefs,
  saveUiPrefs,
} from "@/lib/persistence";
import { SAMPLE_ITEMS_THRESHOLD } from "@/lib/csv/prepare";

export type WizardStep = "upload" | "audit" | "classement";

export type ProviderMode = "cloud" | "local";

export type TokenOptions = {
  filterColumns: boolean;
  cleanDates: boolean;
  sampleItems: boolean;
  sampleItemsN: number;
  includeDescription: boolean;
  /** Injecter les mesures automatiques (volumétrie + formats) dans le prompt
   *  d'audit comme chiffres de référence. Cf. backend core.audit_scan. */
  autoMeasures: boolean;
};

// Options qui mettent en forme le CSV téléchargé (appliquées à l'export
// uniquement). Préférences habituelles, persistées entre sessions et
// indépendantes des projets — cf. `loadUiPrefs`/`saveUiPrefs`.
export type ExportOptions = {
  /** Titre des dossiers (RecordGrp) = nom technique de l'arborescence (File). */
  folderTitleFromFile: boolean;
  /** Titre des fichiers (Item) = titre d'origine importé (rejette le renommage IA). */
  keepOriginalFileTitle: boolean;
};

export type WizardState = {
  step: WizardStep;
  // Source orientée mode (Cloud / Local) — éditée par la sidebar.
  providerMode: ProviderMode;
  cloudModel: string;
  localEndpoint: string;
  localModel: string;
  apiKey: string;
  // Valeurs effectives dérivées, envoyées aux routes API (jamais éditées directement).
  modelId: string;
  baseUrl: string;
  csvFilename: string;
  csvOriginal: SedaRow[] | null;
  csvErrors: string[];
  archivisteObservation: string;
  // Racine du vrac local mémorisée pour l'import direct d'un dossier (scan) —
  // partagée avec l'écran d'import. "" tant qu'aucun dossier n'a été désigné.
  sourceRoot: string;
  tokenOptions: TokenOptions;
  exportOptions: ExportOptions;
  classementBatchSize: number;
  // Mode « plan seul » : l'audit ne demande que le plan de classement (sans
  // état des lieux ni notes). Préférence conservée comme les options de tokens.
  briefMode: boolean;
  auditRunning: boolean;
  thinkingAudit: string;
  rapportAudit: string;
  planValide: string;
  planValideOriginal: string;
  planNotes: string;
  planModifie: boolean;
  classementRunning: boolean;
  thinkingClassement: string;
  llmRawResponse: string;
  llmRawRows: LlmClassementRow[] | null;
  classementBatches: ClassementBatch[] | null;
  csvFinal: ResipResult | null;
  lastError: string;
  usageAudit: LlmUsage | null;
  usageClassementTotal: LlmUsage | null;
  // Durée de traitement réelle (ms) par agent — mesure de performance. Toujours
  // disponible, même quand le serveur local n'expose pas le décompte de tokens.
  durationAudit: number | null;
  durationClassementTotal: number | null;
  settingsModalOpen: boolean;
  // Identité du projet courant (clé de stockage + nom affiché). Vit dans le
  // store — et non en state local d'un composant — pour être posée *atomiquement*
  // avec le snapshot au chargement : sinon l'auto-save voit des données sans
  // stem et crée un doublon. "" = projet non encore matérialisé.
  currentStem: string;
  currentName: string;

  setStep: (s: WizardStep) => void;
  setSettingsModalOpen: (open: boolean) => void;
  setProviderMode: (m: ProviderMode) => void;
  setCloudModel: (m: string) => void;
  setLocalEndpoint: (u: string) => void;
  setLocalModel: (m: string) => void;
  setApiKey: (k: string) => void;
  setTokenOptions: (o: Partial<TokenOptions>) => void;
  setExportOptions: (o: Partial<ExportOptions>) => void;
  setClassementBatchSize: (n: number) => void;
  setBriefMode: (b: boolean) => void;
  setArchivisteObservation: (s: string) => void;
  setSourceRoot: (s: string) => void;
  setCsv: (filename: string, rows: SedaRow[], errors: string[]) => void;
  setAuditRunning: (b: boolean) => void;
  setAuditResult: (rapport: string, thinking: string, plan: string, notes: string) => void;
  setPlanValide: (plan: string) => void;
  resetPlan: () => void;
  // Adopter un plan fourni par l'archiviste, sans audit IA (le pose comme plan
  // validé et repart d'un état sans métadonnée d'audit ni classement).
  adoptPlan: (plan: string) => void;
  setClassementRunning: (b: boolean) => void;
  setClassementResult: (
    raw: string,
    thinking: string,
    result: ResipResult | null,
    rawRows?: LlmClassementRow[] | null,
  ) => void;
  setClassementBatches: (b: ClassementBatch[] | null) => void;
  setLastError: (e: string) => void;
  setUsageAudit: (u: LlmUsage | null) => void;
  setUsageClassementTotal: (u: LlmUsage | null) => void;
  setDurationAudit: (ms: number | null) => void;
  setDurationClassementTotal: (ms: number | null) => void;
  reset: () => void;
  /** Efface audit + classement, garde le CSV chargé et la config LLM/tokens. */
  resetAudit: () => void;
  /**
   * Hydrate l'état depuis un projet stocké **et** pose son identité (stem/nom)
   * dans le même `set()` — atomique, pour que l'auto-save ne voie jamais des
   * données sans stem (sinon : doublon créé au nom du CSV).
   */
  applyProjectSnapshot: (
    snapshot: ProjectSnapshot,
    stem: string,
    name: string,
  ) => void;
  /** Pose l'identité du projet courant (après création auto, renommage…). */
  setCurrentProject: (stem: string, name: string) => void;
  /** Restaure modèle / serveur / clé API depuis le localStorage (appel client). */
  hydrateLlmConfig: () => void;
  /** Restaure les options d'export (préférences habituelles) depuis le localStorage. */
  hydrateUiPrefs: () => void;
};

export type ProjectSnapshot = {
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
  csvFinal: ResipResult | null;
  lastError: string;
};

const initialTokenOptions: TokenOptions = {
  filterColumns: true,
  cleanDates: true,
  sampleItems: false,
  sampleItemsN: 5,
  includeDescription: false,
  autoMeasures: true,
};

type LlmSource = Pick<
  WizardState,
  "providerMode" | "cloudModel" | "localEndpoint" | "localModel"
>;

/** Calcule les valeurs effectives { modelId, baseUrl } envoyées aux routes API. */
function deriveEffective(s: LlmSource): { modelId: string; baseUrl: string } {
  return s.providerMode === "local"
    ? {
        modelId: s.localModel.trim() || LOCAL_MODEL_FALLBACK,
        baseUrl: s.localEndpoint.trim(),
      }
    : { modelId: s.cloudModel, baseUrl: "" };
}

/** Persiste la config LLM (sans les valeurs dérivées). */
function persistLlmSource(s: LlmSource & { apiKey: string }): void {
  saveLlmConfig({
    providerMode: s.providerMode,
    cloudModel: s.cloudModel,
    apiKey: s.apiKey,
    localEndpoint: s.localEndpoint,
    localModel: s.localModel,
  });
}

export const useWizard = create<WizardState>((set) => ({
  step: "upload",
  providerMode: "cloud",
  cloudModel: DEFAULT_MODEL,
  localEndpoint: "",
  localModel: "",
  apiKey: "",
  modelId: DEFAULT_MODEL,
  baseUrl: "",
  csvFilename: "",
  csvOriginal: null,
  csvErrors: [],
  archivisteObservation: "",
  sourceRoot: "",
  tokenOptions: initialTokenOptions,
  briefMode: false,
  exportOptions: { folderTitleFromFile: false, keepOriginalFileTitle: false },
  classementBatchSize: 400,
  auditRunning: false,
  thinkingAudit: "",
  rapportAudit: "",
  planValide: "",
  planValideOriginal: "",
  planNotes: "",
  planModifie: false,
  classementRunning: false,
  thinkingClassement: "",
  llmRawResponse: "",
  llmRawRows: null,
  classementBatches: null,
  csvFinal: null,
  lastError: "",
  usageAudit: null,
  usageClassementTotal: null,
  durationAudit: null,
  durationClassementTotal: null,
  settingsModalOpen: false,
  currentStem: "",
  currentName: "",

  setStep: (s) => set({ step: s }),
  setSettingsModalOpen: (settingsModalOpen) => set({ settingsModalOpen }),
  setProviderMode: (providerMode) =>
    set((s) => {
      const next = { ...s, providerMode };
      persistLlmSource(next);
      return { providerMode, ...deriveEffective(next) };
    }),
  setCloudModel: (cloudModel) =>
    set((s) => {
      const next = { ...s, cloudModel };
      persistLlmSource(next);
      return { cloudModel, ...deriveEffective(next) };
    }),
  setLocalEndpoint: (localEndpoint) =>
    set((s) => {
      const next = { ...s, localEndpoint };
      persistLlmSource(next);
      return { localEndpoint, ...deriveEffective(next) };
    }),
  setLocalModel: (localModel) =>
    set((s) => {
      const next = { ...s, localModel };
      persistLlmSource(next);
      return { localModel, ...deriveEffective(next) };
    }),
  setApiKey: (apiKey) =>
    set((s) => {
      persistLlmSource({ ...s, apiKey });
      return { apiKey };
    }),
  setTokenOptions: (o) =>
    set((state) => ({ tokenOptions: { ...state.tokenOptions, ...o } })),
  setExportOptions: (o) =>
    set((state) => {
      const exportOptions = { ...state.exportOptions, ...o };
      saveUiPrefs(exportOptions);
      return { exportOptions };
    }),
  setClassementBatchSize: (classementBatchSize) =>
    set({ classementBatchSize }),
  setBriefMode: (briefMode) => set({ briefMode }),
  setArchivisteObservation: (archivisteObservation) =>
    set({ archivisteObservation }),
  setSourceRoot: (sourceRoot) => set({ sourceRoot }),
  setCsv: (csvFilename, rows, csvErrors) =>
    set((state) => ({
      csvFilename,
      csvOriginal: rows,
      csvErrors,
      // Active l'échantillonnage automatiquement si le nombre de fichiers
      // dépasse le seuil ; sinon on transmet le CSV entier.
      tokenOptions: {
        ...state.tokenOptions,
        sampleItems:
          rows.filter((r) => r["Content.DescriptionLevel"] === "Item").length >
          SAMPLE_ITEMS_THRESHOLD,
      },
      rapportAudit: "",
      thinkingAudit: "",
      planValide: "",
      planValideOriginal: "",
      planNotes: "",
      planModifie: false,
      csvFinal: null,
      llmRawResponse: "",
      llmRawRows: null,
      classementBatches: null,
      lastError: "",
      step: "upload",
    })),
  setAuditRunning: (auditRunning) => set({ auditRunning }),
  setAuditResult: (rapportAudit, thinkingAudit, plan, planNotes) =>
    set({
      rapportAudit,
      thinkingAudit,
      planValide: plan,
      planValideOriginal: plan,
      planNotes,
      planModifie: false,
    }),
  setPlanValide: (planValide) =>
    set((state) => ({
      planValide,
      planModifie: planValide !== state.planValideOriginal,
    })),
  resetPlan: () =>
    set((state) => ({
      planValide: state.planValideOriginal,
      planModifie: false,
    })),
  adoptPlan: (plan) =>
    set({
      planValide: plan,
      planValideOriginal: plan,
      planNotes: "",
      planModifie: false,
      // Plan fourni directement : aucune métadonnée d'audit.
      rapportAudit: "",
      thinkingAudit: "",
      usageAudit: null,
      durationAudit: null,
      // Repart d'un classement vierge.
      csvFinal: null,
      llmRawResponse: "",
      llmRawRows: null,
      classementBatches: null,
      lastError: "",
    }),
  setClassementRunning: (classementRunning) => set({ classementRunning }),
  setClassementResult: (
    llmRawResponse,
    thinkingClassement,
    csvFinal,
    llmRawRows = null,
  ) =>
    set({ llmRawResponse, thinkingClassement, csvFinal, llmRawRows }),
  setClassementBatches: (classementBatches) => set({ classementBatches }),
  setLastError: (lastError) => set({ lastError }),
  setUsageAudit: (usageAudit) => set({ usageAudit }),
  setUsageClassementTotal: (usageClassementTotal) => set({ usageClassementTotal }),
  setDurationAudit: (durationAudit) => set({ durationAudit }),
  setDurationClassementTotal: (durationClassementTotal) => set({ durationClassementTotal }),
  reset: () =>
    set({
      step: "upload",
      csvFilename: "",
      csvOriginal: null,
      csvErrors: [],
      archivisteObservation: "",
      rapportAudit: "",
      thinkingAudit: "",
      planValide: "",
      planValideOriginal: "",
      planNotes: "",
      planModifie: false,
      csvFinal: null,
      llmRawResponse: "",
      llmRawRows: null,
      classementBatches: null,
      thinkingClassement: "",
      lastError: "",
      usageAudit: null,
      usageClassementTotal: null,
      durationAudit: null,
      durationClassementTotal: null,
      // Nouveau projet : on repart sans identité (rien à auto-sauvegarder tant
      // qu'un premier résultat IA n'a pas matérialisé un projet).
      currentStem: "",
      currentName: "",
    }),
  resetAudit: () =>
    set({
      step: "audit",
      archivisteObservation: "",
      rapportAudit: "",
      thinkingAudit: "",
      planValide: "",
      planValideOriginal: "",
      planNotes: "",
      planModifie: false,
      csvFinal: null,
      llmRawResponse: "",
      llmRawRows: null,
      classementBatches: null,
      thinkingClassement: "",
      lastError: "",
      usageAudit: null,
      usageClassementTotal: null,
      durationAudit: null,
      durationClassementTotal: null,
    }),
  applyProjectSnapshot: (snapshot, stem, name) =>
    set({
      step: snapshot.step,
      csvFilename: snapshot.csvFilename,
      csvOriginal: snapshot.csvOriginal,
      csvErrors: [],
      archivisteObservation: snapshot.archivisteObservation,
      rapportAudit: snapshot.rapportAudit,
      thinkingAudit: snapshot.thinkingAudit,
      planValide: snapshot.planValide,
      planValideOriginal: snapshot.planValideOriginal,
      planNotes: snapshot.planNotes,
      planModifie: snapshot.planModifie,
      briefMode: snapshot.briefMode ?? false,
      thinkingClassement: snapshot.thinkingClassement,
      llmRawResponse: snapshot.llmRawResponse,
      llmRawRows: snapshot.llmRawRows,
      classementBatches: snapshot.classementBatches ?? null,
      csvFinal: snapshot.csvFinal,
      lastError: snapshot.lastError,
      // Mesures de session non persistées (comme usageAudit/usageClassementTotal) :
      // on repart à zéro au chargement d'un projet.
      usageAudit: null,
      usageClassementTotal: null,
      durationAudit: null,
      durationClassementTotal: null,
      // Identité posée dans le même set() que les données → pas de fenêtre où
      // l'auto-save verrait un rapport sans stem.
      currentStem: stem,
      currentName: name,
    }),
  setCurrentProject: (currentStem, currentName) =>
    set({ currentStem, currentName }),
  hydrateLlmConfig: () => {
    const cfg = loadLlmConfig();
    if (!cfg) return;
    set((s) => {
      const source: LlmSource = {
        providerMode: cfg.providerMode ?? s.providerMode,
        cloudModel: cfg.cloudModel ?? s.cloudModel,
        localEndpoint: cfg.localEndpoint ?? s.localEndpoint,
        localModel: cfg.localModel ?? s.localModel,
      };
      return {
        ...source,
        apiKey: cfg.apiKey ?? s.apiKey,
        ...deriveEffective(source),
      };
    });
  },
  hydrateUiPrefs: () => {
    const prefs = loadUiPrefs();
    if (!prefs) return;
    set((s) => ({
      exportOptions: {
        folderTitleFromFile:
          prefs.folderTitleFromFile ?? s.exportOptions.folderTitleFromFile,
        keepOriginalFileTitle:
          prefs.keepOriginalFileTitle ?? s.exportOptions.keepOriginalFileTitle,
      },
    }));
  },
}));
