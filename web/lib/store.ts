import { create } from "zustand";
import type {
  SedaRow,
  ResipResult,
  LlmClassementRow,
  ClassementBatch,
  ClassementDirective,
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
import { MAX_CLASSEMENT_CONCURRENCY } from "@/lib/csv/batch-schedule";

export type WizardStep = "upload" | "audit" | "classement";

export type ProviderMode = "cloud" | "local";

// Origine du plan de classement retenu. `"audit_llm"` = produit par
// AUD-001 ; `"fourni"` = plan apporté par l'archiviste et adopté **sans appel LLM**
// (import ou aller-retour Explorateur). `null` = pas encore de plan.
// Consigné dans le projet, le journal de traitement et l'export du rapport.
export type PlanOrigin = "audit_llm" | "fourni" | null;

export type TokenOptions = {
  filterColumns: boolean;
  cleanDates: boolean;
  sampleItems: boolean;
  sampleItemsN: number;
  /** Arborescence seule : n'envoyer que les dossiers à l'audit, aucun fichier
   *  (Item). Prime sur l'échantillonnage. Sans effet sur le classement, qui
   *  traite toujours tous les fichiers. Portée : audit (mappé sur le contrat
   *  moteur `includeItems = !foldersOnly`). */
  foldersOnly: boolean;
  includeDescription: boolean;
  /** Injecter les mesures automatiques (volumétrie + formats) dans le prompt
   *  d'audit comme chiffres de référence. Cf. backend core.audit_scan. */
  autoMeasures: boolean;
  /** Demander l'« avis de classement » (la « Démarche de l'IA ») au classement.
   *  Désactiver retire le bloc d'instruction du prompt CLA-001 — moins de tokens
   *  de sortie, mais plus de panneau « Démarche de l'IA ». Portée : classement. */
  classementAvis: boolean;
  /** Méthode d'identifiant au classement (cf. backend prompts.CLA_001).
   *  false (défaut) = « Path » : le modèle recopie le chemin complet en sortie
   *  (ancrage fort, meilleure finesse, sortie plus longue/lente).
   *  true = « Ref » : le modèle ne recopie qu'un entier court (sortie rapide,
   *  ancrage moindre — réhydraté côté backend). Portée : classement. */
  classementRef: boolean;
};

// Options qui mettent en forme le CSV téléchargé (appliquées à l'export
// uniquement). Préférences habituelles, persistées entre sessions et
// indépendantes des projets — cf. `loadUiPrefs`/`saveUiPrefs`.
export type ExportOptions = {
  /** Titre des dossiers (RecordGrp) = nom technique de l'arborescence (File). */
  folderTitleFromFile: boolean;
  /** Titre des fichiers (Item) = titre d'origine importé (rejette le renommage IA). */
  keepOriginalFileTitle: boolean;
  /**
   * Retire le préfixe de position des noms de dossier (`1-1_` → ``) dans le CSV,
   * le manifeste et la copie physique. Contrairement aux deux options ci-dessus
   * (pures cosmétiques de titre appliquées au téléchargement), celle-ci touche la
   * colonne `File` : elle est appliquée **côté moteur** au finalize
   * (`stripFolderNumbers`), donc une bascule après coup **re-finalise** (passe
   * Python pure, sans LLM). Défaut off : les numéros ordonnent le fonds.
   */
  stripFolderNumbers: boolean;
};

export type WizardState = {
  step: WizardStep;
  // Source orientée mode (Cloud / Local) — éditée par la sidebar.
  providerMode: ProviderMode;
  cloudModel: string;
  localEndpoint: string;
  localModel: string;
  apiKey: string;
  // La clé API n'est persistée en clair dans `localStorage` que sur opt-in
  // explicite. `false` (défaut) = session-only : la clé vit en mémoire le temps
  // de la session et est oubliée au rechargement.
  rememberApiKey: boolean;
  // Valeurs effectives dérivées, envoyées aux routes API (jamais éditées directement).
  modelId: string;
  baseUrl: string;
  csvFilename: string;
  csvOriginal: SedaRow[] | null;
  csvErrors: string[];
  // Racine locale du vrac — mémorisée pour pré-remplir l'import direct
  // d'un dossier, l'enrichissement et l'application physique. ""
  // = non renseignée. Backend local uniquement ; simple chemin (aucune donnée).
  sourceRoot: string;
  archivisteObservation: string;
  tokenOptions: TokenOptions;
  exportOptions: ExportOptions;
  classementBatchSize: number;
  // Lots CLA-001 traités en parallèle — séquentiel (1) par défaut, borné à
  // MAX_CLASSEMENT_CONCURRENCY. Forcé à 1 pour un serveur local (mono-requête),
  // garde appliquée au lancement du classement (miroir du CLI `--concurrency`).
  classementConcurrency: number;
  // Donner le rapport d'audit du projet en contexte à l'agent (0.6.0). ON par
  // défaut ; sans effet tant qu'aucun rapport n'existe. Réglage conservé entre
  // sessions ; le changer recrée la session de l'agent (contexte figé à la création).
  agentUseAuditReport: boolean;
  // Mode « plan seul » : l'audit ne demande que le plan de classement (sans
  // état des lieux ni notes). Préférence conservée comme les options de tokens.
  briefMode: boolean;
  // Plan de classement de référence injecté comme contrainte à l'audit.
  // `referencePlan` = bloc arborescence dérivé du CSV Resip « dossiers seuls »
  // importé par l'archiviste (`POST /reference-plan/from-csv`), "" = aucun ;
  // `referencePlanName` = nom du fichier importé (affichage) ; `referenceMode`
  // ∈ {inspire, conform} règle le registre. L'injection est faite côté moteur
  // (le front ne transporte que le bloc et le mode — aucune logique métier).
  referencePlan: string;
  referencePlanName: string;
  referenceMode: string;
  auditRunning: boolean;
  thinkingAudit: string;
  rapportAudit: string;
  planValide: string;
  planValideOriginal: string;
  planNotes: string;
  planModifie: boolean;
  // Origine du plan retenu : produit par l'audit LLM ou fourni par
  // l'archiviste (bypass de l'audit). Piloté par `setAuditResult` / `adoptPlan`.
  planOrigin: PlanOrigin;
  // Consignes de classement de l'archiviste : préconisations ancrées à un
  // dossier du plan ou au niveau du fonds, injectées dans CLA-001 et **réutilisées
  // à chaque relance**. Persistées au projet. Transport pur.
  classementDirectives: ClassementDirective[];
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
  // Version du prompt utilisé par agent — renvoyée par le backend dans le
  // done{} SSE, consignée dans le projet et les exports pour interpréter
  // d'anciens résultats après une évolution des prompts.
  promptVersionAudit: string | null;
  promptVersionClassement: string | null;
  // Modèle réellement utilisé par agent — figé à l'exécution (renvoyé par le
  // backend dans le done{} SSE), persisté et affiché pour la traçabilité : après
  // un rechargement ou un changement de modèle, on sait quel modèle a produit
  // quoi. Le réglage courant (`modelId`) peut diverger de ces valeurs figées.
  modelAudit: string | null;
  modelClassement: string | null;
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
  setRememberApiKey: (b: boolean) => void;
  setTokenOptions: (o: Partial<TokenOptions>) => void;
  setExportOptions: (o: Partial<ExportOptions>) => void;
  setClassementBatchSize: (n: number) => void;
  setClassementConcurrency: (n: number) => void;
  setAgentUseAuditReport: (b: boolean) => void;
  setBriefMode: (b: boolean) => void;
  setReferencePlan: (tree: string, name: string) => void;
  setReferenceMode: (mode: string) => void;
  setArchivisteObservation: (s: string) => void;
  setSourceRoot: (s: string) => void;
  setCsv: (filename: string, rows: SedaRow[], errors: string[]) => void;
  setAuditRunning: (b: boolean) => void;
  setAuditResult: (rapport: string, thinking: string, plan: string, notes: string) => void;
  /**
   * Adopte un plan fourni par l'archiviste **sans appel LLM** : pose le plan
   * comme validé, marque l'origine « fourni », et **n'invente aucune métadonnée
   * d'audit** (usage tokens, version de prompt, modèle d'audit remis à zéro).
   * Le rapport et les notes d'audit sont vidés (aucun audit n'a eu lieu).
   */
  adoptPlan: (plan: string) => void;
  setPlanValide: (plan: string) => void;
  setClassementDirectives: (d: ClassementDirective[]) => void;
  resetPlan: () => void;
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
  setPromptVersionAudit: (v: string | null) => void;
  setPromptVersionClassement: (v: string | null) => void;
  setModelAudit: (m: string | null) => void;
  setModelClassement: (m: string | null) => void;
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
  // Origine du plan — optionnel (absent des projets antérieurs → null).
  planOrigin?: PlanOrigin;
  // Consignes de classement — optionnel (absent des projets antérieurs → []).
  classementDirectives?: ClassementDirective[];
  // Racine locale du vrac — optionnel (absent des projets antérieurs → "").
  sourceRoot?: string;
  briefMode: boolean;
  // Plan de référence retenu pour l'audit — optionnels (absents des projets
  // antérieurs ; "" / "inspire" par défaut).
  referencePlan?: string;
  referencePlanName?: string;
  referenceMode?: string;
  thinkingClassement: string;
  llmRawResponse: string;
  llmRawRows: LlmClassementRow[] | null;
  classementBatches: ClassementBatch[] | null;
  csvFinal: ResipResult | null;
  lastError: string;
  // Mesures réelles du dernier traitement (tokens + durée par agent). Optionnelles
  // — absentes des projets enregistrés avant cette version, ou si le serveur
  // local n'expose pas les tokens.
  usageAudit?: LlmUsage | null;
  usageClassementTotal?: LlmUsage | null;
  durationAudit?: number | null;
  durationClassementTotal?: number | null;
  // Versions de prompt — absentes des projets antérieurs.
  promptVersionAudit?: string | null;
  promptVersionClassement?: string | null;
  // Modèle utilisé par agent — figé à l'exécution, absent des projets antérieurs.
  modelAudit?: string | null;
  modelClassement?: string | null;
};

const initialTokenOptions: TokenOptions = {
  filterColumns: true,
  cleanDates: true,
  sampleItems: false,
  sampleItemsN: 5,
  foldersOnly: false,
  includeDescription: false,
  autoMeasures: true,
  classementAvis: true,
  classementRef: false,
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

/** Persiste la config LLM (sans les valeurs dérivées). La clé API n'est écrite
 *  que si `rememberApiKey` est vrai — la garde est appliquée dans
 * `saveLlmConfig` (frontière du stockage). */
function persistLlmSource(
  s: LlmSource & { apiKey: string; rememberApiKey: boolean },
): void {
  saveLlmConfig({
    providerMode: s.providerMode,
    cloudModel: s.cloudModel,
    apiKey: s.apiKey,
    rememberApiKey: s.rememberApiKey,
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
  rememberApiKey: false,
  modelId: DEFAULT_MODEL,
  baseUrl: "",
  csvFilename: "",
  csvOriginal: null,
  csvErrors: [],
  sourceRoot: "",
  archivisteObservation: "",
  tokenOptions: initialTokenOptions,
  briefMode: false,
  referencePlan: "",
  referencePlanName: "",
  referenceMode: "inspire",
  exportOptions: {
    folderTitleFromFile: false,
    keepOriginalFileTitle: false,
    stripFolderNumbers: false,
  },
  classementBatchSize: 400,
  classementConcurrency: 1,
  agentUseAuditReport: true,
  auditRunning: false,
  thinkingAudit: "",
  rapportAudit: "",
  planValide: "",
  planValideOriginal: "",
  planNotes: "",
  planModifie: false,
  planOrigin: null,
  classementDirectives: [],
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
  promptVersionAudit: null,
  promptVersionClassement: null,
  modelAudit: null,
  modelClassement: null,
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
  // Bascule la mémorisation de la clé. Activer réécrit la config avec la
  // clé courante ; désactiver la réécrit sans la clé (effaçant tout secret déjà
  // posé sur disque) tout en la gardant en mémoire pour la session.
  setRememberApiKey: (rememberApiKey) =>
    set((s) => {
      persistLlmSource({ ...s, rememberApiKey });
      return { rememberApiKey };
    }),
  setTokenOptions: (o) =>
    set((state) => {
      const tokenOptions = { ...state.tokenOptions, ...o };
      // `classementAvis` / `classementRef` sont des habitudes (réglages
      // laboratoire), persistées entre sessions comme les options d'export —
      // contrairement aux autres optimisations, recalculées par projet/CSV.
      if ("classementAvis" in o || "classementRef" in o) {
        saveUiPrefs({
          classementAvis: tokenOptions.classementAvis,
          classementRef: tokenOptions.classementRef,
        });
      }
      return { tokenOptions };
    }),
  setExportOptions: (o) =>
    set((state) => {
      const exportOptions = { ...state.exportOptions, ...o };
      saveUiPrefs(exportOptions);
      return { exportOptions };
    }),
  setClassementBatchSize: (classementBatchSize) => {
    // Réglage de traitement conservé entre sessions (comme les options d'export).
    saveUiPrefs({ classementBatchSize });
    set({ classementBatchSize });
  },
  setClassementConcurrency: (classementConcurrency) => {
    saveUiPrefs({ classementConcurrency });
    set({ classementConcurrency });
  },
  setAgentUseAuditReport: (agentUseAuditReport) => {
    saveUiPrefs({ agentUseAuditReport });
    set({ agentUseAuditReport });
  },
  setBriefMode: (briefMode) => set({ briefMode }),
  setReferencePlan: (referencePlan, referencePlanName) =>
    set({ referencePlan, referencePlanName }),
  setReferenceMode: (referenceMode) => set({ referenceMode }),
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
      planOrigin: null,
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
      // Un plan issu de l'audit LLM (dès qu'un plan est produit).
      planOrigin: plan ? "audit_llm" : null,
    }),
  // Plan fourni par l'archiviste adopté sans appel LLM : on vide tout
  // artefact d'audit (rapport, notes, mesures, versions, modèle) pour ne rien
  // fabriquer, et on marque l'origine « fourni ».
  adoptPlan: (plan) =>
    set({
      planValide: plan,
      planValideOriginal: plan,
      planModifie: false,
      planOrigin: "fourni",
      rapportAudit: "",
      thinkingAudit: "",
      planNotes: "",
      usageAudit: null,
      durationAudit: null,
      promptVersionAudit: null,
      modelAudit: null,
    }),
  setPlanValide: (planValide) =>
    set((state) => ({
      planValide,
      planModifie: planValide !== state.planValideOriginal,
    })),
  setClassementDirectives: (classementDirectives) => set({ classementDirectives }),
  resetPlan: () =>
    set((state) => ({
      planValide: state.planValideOriginal,
      planModifie: false,
    })),
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
  setPromptVersionAudit: (promptVersionAudit) => set({ promptVersionAudit }),
  setPromptVersionClassement: (promptVersionClassement) =>
    set({ promptVersionClassement }),
  setModelAudit: (modelAudit) => set({ modelAudit }),
  setModelClassement: (modelClassement) => set({ modelClassement }),
  reset: () =>
    set({
      step: "upload",
      csvFilename: "",
      csvOriginal: null,
      csvErrors: [],
      sourceRoot: "",
      archivisteObservation: "",
      referencePlan: "",
      referencePlanName: "",
      referenceMode: "inspire",
      rapportAudit: "",
      thinkingAudit: "",
      planValide: "",
      planValideOriginal: "",
      planNotes: "",
      planModifie: false,
      planOrigin: null,
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
      promptVersionAudit: null,
      promptVersionClassement: null,
      modelAudit: null,
      modelClassement: null,
      // Nouveau projet : on repart sans identité (rien à auto-sauvegarder tant
      // qu'un premier acquis — rapport d'audit ou plan adopté — n'a pas
      // matérialisé un projet, cf. `sidebar.tsx`).
      currentStem: "",
      currentName: "",
    }),
  resetAudit: () =>
    set({
      step: "audit",
      archivisteObservation: "",
      referencePlan: "",
      referencePlanName: "",
      referenceMode: "inspire",
      rapportAudit: "",
      thinkingAudit: "",
      planValide: "",
      planValideOriginal: "",
      planNotes: "",
      planModifie: false,
      planOrigin: null,
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
      promptVersionAudit: null,
      promptVersionClassement: null,
      modelAudit: null,
      modelClassement: null,
    }),
  applyProjectSnapshot: (snapshot, stem, name) =>
    set({
      step: snapshot.step,
      csvFilename: snapshot.csvFilename,
      csvOriginal: snapshot.csvOriginal,
      csvErrors: [],
      sourceRoot: snapshot.sourceRoot ?? "",
      archivisteObservation: snapshot.archivisteObservation,
      rapportAudit: snapshot.rapportAudit,
      thinkingAudit: snapshot.thinkingAudit,
      planValide: snapshot.planValide,
      planValideOriginal: snapshot.planValideOriginal,
      planNotes: snapshot.planNotes,
      planModifie: snapshot.planModifie,
      planOrigin: snapshot.planOrigin ?? (snapshot.planValide ? "audit_llm" : null),
      classementDirectives: snapshot.classementDirectives ?? [],
      briefMode: snapshot.briefMode ?? false,
      referencePlan: snapshot.referencePlan ?? "",
      referencePlanName: snapshot.referencePlanName ?? "",
      referenceMode: snapshot.referenceMode ?? "inspire",
      thinkingClassement: snapshot.thinkingClassement,
      llmRawResponse: snapshot.llmRawResponse,
      llmRawRows: snapshot.llmRawRows,
      classementBatches: snapshot.classementBatches ?? null,
      csvFinal: snapshot.csvFinal,
      lastError: snapshot.lastError,
      // Mesures réelles du dernier traitement, restaurées avec le projet (absentes
      // des projets enregistrés avant cette version → null).
      usageAudit: snapshot.usageAudit ?? null,
      usageClassementTotal: snapshot.usageClassementTotal ?? null,
      durationAudit: snapshot.durationAudit ?? null,
      durationClassementTotal: snapshot.durationClassementTotal ?? null,
      promptVersionAudit: snapshot.promptVersionAudit ?? null,
      promptVersionClassement: snapshot.promptVersionClassement ?? null,
      modelAudit: snapshot.modelAudit ?? null,
      modelClassement: snapshot.modelClassement ?? null,
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
        rememberApiKey: cfg.rememberApiKey ?? s.rememberApiKey,
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
        stripFolderNumbers:
          prefs.stripFolderNumbers ?? s.exportOptions.stripFolderNumbers,
      },
      tokenOptions: {
        ...s.tokenOptions,
        classementAvis: prefs.classementAvis ?? s.tokenOptions.classementAvis,
        classementRef: prefs.classementRef ?? s.tokenOptions.classementRef,
      },
      // Réglages de traitement par lot — bornés à la relecture (une valeur
      // corrompue/hors bornes ne doit jamais casser le découpage ou la garde).
      classementBatchSize:
        typeof prefs.classementBatchSize === "number"
          ? Math.max(50, Math.round(prefs.classementBatchSize))
          : s.classementBatchSize,
      classementConcurrency:
        typeof prefs.classementConcurrency === "number"
          ? Math.min(
              MAX_CLASSEMENT_CONCURRENCY,
              Math.max(1, Math.round(prefs.classementConcurrency)),
            )
          : s.classementConcurrency,
      agentUseAuditReport:
        typeof prefs.agentUseAuditReport === "boolean"
          ? prefs.agentUseAuditReport
          : s.agentUseAuditReport,
    }));
  },
}));
