"use client";

import { useState, useRef, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { useWizard } from "@/lib/store";
import { useT } from "@/lib/i18n";
import { stringifyCsv } from "@/lib/csv/parse";
import {
  REFONTE_LIBRE,
  appendNoteTemplate,
} from "@/lib/note-templates";
import { stripStructureMarkers } from "@/lib/csv/extract";
import { parsePlanTree } from "@/lib/csv/plan-tree";
import {
  streamSse,
  postJson,
  formatApiError,
  referencePlanFromCsv,
  comparePlans,
  planFromFile,
  type ReferencePlanFromCsv,
  type PlanCompareResult,
  type LlmUsage,
} from "@/lib/llm/client-stream";
import { DEMO_MODE } from "@/lib/llm/config";
import { PlanExplorerPanel } from "@/components/wizard/plan-explorer-panel";
import { PlanFolderPicker } from "@/components/wizard/plan-folder-picker";
import { TokenUsageBar } from "@/components/token-usage-bar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { InfoTip } from "@/components/ui/info-tip";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { StreamingMarkdown } from "@/components/streaming-markdown";
import { MarkdownToc } from "@/components/markdown-toc";
import { ThinkingPanel } from "@/components/thinking-panel";
import { PlanTreeEditor } from "@/components/plan-tree-editor";
import { PlanTree } from "@/components/plan-tree";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { IconAction } from "@/components/wizard/icon-action";
import { StepActions } from "@/components/wizard/step-actions";
import {
  AlertCircle,
  AlertTriangle,
  Download,
  RotateCcw,
  StickyNote,
  BarChart3,
  ClipboardList,
  Pin,
  ListTree,
  Pencil,
  Loader2,
  CircleStop,
  ArrowRight,
  Info,
  FileText,
  Printer,
  Library,
  Layers,
  GitCompare,
  Check,
} from "lucide-react";

// Audit comparatif multi-plans : nombre de propositions de plan que
// l'archiviste peut demander en une fois. Borné comme le moteur (MAX_VARIANTS=5).
const VARIANT_COUNTS = [1, 2, 3, 4, 5] as const;

// Vue du plan dans l'onglet « Plan » de l'audit. brut = texte renvoyé par l'IA
// (lecture seule) ; tree = arborescence pliable (lecture seule) ; edit = éditeur
// d'arbre structuré (l'édition du plan vit à l'étape audit).
type PlanView = "brut" | "tree" | "edit";

// Une variante de plan collectée par un audit (avant comparaison/choix). On garde
// le travail complet du modèle pour pouvoir l'adopter tel quel (rapport, notes,
// usage, durée, version de prompt) — comme un audit simple.
type AuditVariant = {
  report: string;
  reasoning: string;
  plan: string;
  notes: string;
  usage: LlmUsage | null;
  durationMs: number | null;
  promptVersion: string | null;
};

export function StepAudit() {
  const t = useT();
  const {
    csvOriginal,
    archivisteObservation,
    setArchivisteObservation,
    briefMode,
    setBriefMode,
    referencePlan,
    referencePlanName,
    setReferencePlan,
    referenceMode,
    setReferenceMode,
    tokenOptions,
    modelId,
    apiKey,
    baseUrl,
    auditRunning,
    setAuditRunning,
    setAuditResult,
    rapportAudit,
    thinkingAudit,
    planValide,
    planValideOriginal,
    planModifie,
    planOrigin,
    setPlanValide,
    adoptPlan,
    resetPlan,
    planNotes,
    setStep,
    lastError,
    setLastError,
    resetAudit,
    usageAudit,
    setUsageAudit,
    durationAudit,
    setDurationAudit,
    promptVersionAudit,
    setPromptVersionAudit,
    modelAudit,
    setModelAudit,
  } = useWizard();

  const [streamingResponse, setStreamingResponse] = useState("");
  const [streamingThinking, setStreamingThinking] = useState("");
  // Vue du plan dans l'onglet « Plan » : brut (texte IA), visualisation (arbre
  // pliable, lecture seule) ou édition (éditeur d'arbre). L'édition du plan se
  // fait ici, à l'audit (le plan est le livrable de cette étape) ; au classement
  // il n'est plus qu'en lecture seule.
  const [planView, setPlanView] = useState<PlanView>("tree");
  const [confirmReset, setConfirmReset] = useState(false);
  // Plan de classement de référence — importé par l'archiviste sous forme de
  // CSV Resip « dossiers seuls », converti en arborescence côté moteur
  // (`POST /reference-plan/from-csv`). État local du dépôt : chargement, erreurs
  // de validation (bloquantes), avertissements (fichiers ignorés), résumé.
  const [refLoading, setRefLoading] = useState(false);
  const [refErrors, setRefErrors] = useState<string[]>([]);
  const [refWarnings, setRefWarnings] = useState<string[]>([]);
  const [refFolderCount, setRefFolderCount] = useState(0);
  const [refServerError, setRefServerError] = useState<string | null>(null);
  // Audit comparatif multi-plans. `variantCount` = 1 → audit simple
  // (comportement inchangé). > 1 → N audits, comparaison côté moteur, puis choix.
  const [variantCount, setVariantCount] = useState(1);
  const [variantProgress, setVariantProgress] = useState<{
    current: number;
    total: number;
  } | null>(null);
  const [auditVariants, setAuditVariants] = useState<AuditVariant[]>([]);
  const [compareResult, setCompareResult] = useState<PlanCompareResult | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Adoption d'un plan fourni par l'archiviste — bypass de l'audit LLM.
  // État du dépôt : chargement + erreur/avertissements de conversion (moteur).
  const [importPlanLoading, setImportPlanLoading] = useState(false);
  const [importPlanError, setImportPlanError] = useState<string | null>(null);
  const [importPlanWarnings, setImportPlanWarnings] = useState<string[]>([]);

  // Adopte un plan importé (CSV Resip « dossiers seuls » ou Markdown canonique)
  // sans appel LLM : la conversion/validation vit dans le moteur (POST
  // /plan/from-file) ; le front ne transporte que le texte. Une fois adopté,
  // la vue des résultats s'affiche (plan validé, origine « fourni »).
  const applyPlanFile = useCallback(
    async (name: string, content: string) => {
      setImportPlanLoading(true);
      setImportPlanError(null);
      setImportPlanWarnings([]);
      try {
        const res = await planFromFile(name, content);
        adoptPlan(res.plan);
        setImportPlanWarnings(res.warnings);
      } catch (err) {
        setImportPlanError(formatApiError(err));
      } finally {
        setImportPlanLoading(false);
      }
    },
    [adoptPlan],
  );

  const onImportPlanDrop = useCallback(
    async (files: File[]) => {
      const file = files[0];
      if (!file) return;
      await applyPlanFile(file.name, await file.text());
    },
    [applyPlanFile],
  );

  const {
    getRootProps: getImportRootProps,
    getInputProps: getImportInputProps,
    isDragActive: isImportDragActive,
  } = useDropzone({
    onDrop: onImportPlanDrop,
    accept: {
      "text/csv": [".csv"],
      "application/vnd.ms-excel": [".csv"],
      "text/markdown": [".md", ".markdown"],
      "text/plain": [".txt", ".md"],
    },
    multiple: false,
    disabled: auditRunning || importPlanLoading,
  });

  // Import d'un plan de référence : dépôt d'un CSV Resip « dossiers seuls »,
  // converti en arborescence par le moteur. Mêmes contrôles que l'upload de
  // départ (validation bloquante) ; les fichiers présents sont ignorés (warning).
  const applyReferenceCsv = useCallback(
    async (name: string, csv: string) => {
      setRefLoading(true);
      setRefServerError(null);
      setRefErrors([]);
      setRefWarnings([]);
      try {
        const res: ReferencePlanFromCsv = await referencePlanFromCsv(csv);
        if (res.validationErrors.length > 0) {
          setRefErrors(res.validationErrors);
          setReferencePlan("", "");
          setRefFolderCount(0);
          return;
        }
        setReferencePlan(res.tree, name);
        setRefWarnings(res.warnings);
        setRefFolderCount(res.folderCount);
      } catch (err) {
        setRefServerError(formatApiError(err));
        setReferencePlan("", "");
        setRefFolderCount(0);
      } finally {
        setRefLoading(false);
      }
    },
    [setReferencePlan],
  );

  const onReferenceDrop = useCallback(
    async (files: File[]) => {
      const file = files[0];
      if (!file) return;
      await applyReferenceCsv(file.name, await file.text());
    },
    [applyReferenceCsv],
  );

  const clearReference = useCallback(() => {
    setReferencePlan("", "");
    setRefErrors([]);
    setRefWarnings([]);
    setRefFolderCount(0);
    setRefServerError(null);
  }, [setReferencePlan]);

  const {
    getRootProps: getRefRootProps,
    getInputProps: getRefInputProps,
    isDragActive: isRefDragActive,
  } = useDropzone({
    onDrop: onReferenceDrop,
    accept: { "text/csv": [".csv"], "application/vnd.ms-excel": [".csv"] },
    multiple: false,
    disabled: auditRunning || refLoading,
  });

  if (!csvOriginal) {
    return (
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>Aucun CSV chargé</AlertTitle>
        <AlertDescription>
          Revenez à l&apos;étape précédente pour importer un fichier.
        </AlertDescription>
      </Alert>
    );
  }

  const runAudit = async () => {
    setAuditRunning(true);
    setStreamingResponse("");
    setStreamingThinking("");
    setLastError("");

    abortControllerRef.current = new AbortController();

    const prep = {
      filterColumns: tokenOptions.filterColumns,
      cleanDates: tokenOptions.cleanDates,
      sampleItems: tokenOptions.sampleItems,
      sampleItemsN: tokenOptions.sampleItemsN,
      includeItems: !tokenOptions.foldersOnly,
      includeDescription: tokenOptions.includeDescription,
      autoMeasures: tokenOptions.autoMeasures,
    };

    try {
      const result = await streamSse(
        "/audit",
        {
          csv: stringifyCsv(csvOriginal),
          observation: archivisteObservation,
          model: modelId,
          apiKey,
          baseUrl,
          prep,
          brief: briefMode,
          // Plan de référence : le front ne transmet que le bloc arborescence
          // (dérivé du CSV importé) et le mode ; l'injection comme contrainte
          // d'audit est faite côté moteur (`core.reference_plans`) — pas de TS.
          referencePlan,
          referenceMode,
        },
        {
          onText: (delta) => setStreamingResponse((prev) => prev + delta),
          onReasoning: (delta) => setStreamingThinking((prev) => prev + delta),
          // Retry LLM en cours : visible dans le panneau de démarche.
          onNotice: (msg) =>
            setStreamingThinking((prev) => `${prev}\n\n> ⟳ ${msg}\n\n`),
        },
        abortControllerRef.current.signal,
      );

      // Interruption par l'utilisateur. On conserve tout de même le travail déjà produit (rapport partiel + plan/notes ré-extraits sans appel LLM) au lieu de le jeter.
      if (result.aborted) {
        setLastError("Audit arrêté par l'utilisateur");
        if (result.text.trim()) {
          let plan = "";
          let notes = "";
          try {
            const ex = await postJson<{ plan?: string; notes?: string }>(
              "/extract-plans",
              { report: result.text },
            );
            plan = ex.plan ?? "";
            notes = ex.notes ?? "";
          } catch {
            // Ré-extraction best-effort : on conserve au moins le rapport brut.
          }
          setAuditResult(result.text, result.reasoning, plan, notes);
          setUsageAudit(result.usage);
        }
        return;
      }

      const report = (result.done?.report as string) ?? result.text;
      const plan = (result.done?.plan as string) ?? "";
      const notes = (result.done?.notes as string) ?? "";
      setAuditResult(report, result.reasoning, plan, notes);
      setUsageAudit(result.usage);
      setDurationAudit(
        typeof result.done?.durationMs === "number" ? result.done.durationMs : null,
      );
      // Version du prompt AUD-001 — consignée dans le projet et l'export .md.
      setPromptVersionAudit(
        typeof result.done?.promptVersion === "string" ? result.done.promptVersion : null,
      );
      // Modèle ayant exécuté l'audit — figé pour la traçabilité (renvoyé par le
      // backend ; repli sur le modèle envoyé si un ancien backend l'omet).
      setModelAudit(
        typeof result.done?.model === "string" ? result.done.model : modelId,
      );
    } catch (err) {
      setLastError(formatApiError(err));
    } finally {
      setAuditRunning(false);
    }
  };

  // Audit comparatif multi-plans : lance N audits successifs (la
  // stochasticité du modèle différencie les propositions), puis fait comparer les
  // plans obtenus par le moteur (`/plan-compare`). Aucune logique de comparaison
  // en TS — le front ne fait que collecter, transmettre et présenter.
  const runComparison = async () => {
    setAuditRunning(true);
    setLastError("");
    setCompareResult(null);
    setAuditVariants([]);

    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    const prep = {
      filterColumns: tokenOptions.filterColumns,
      cleanDates: tokenOptions.cleanDates,
      sampleItems: tokenOptions.sampleItems,
      sampleItemsN: tokenOptions.sampleItemsN,
      includeItems: !tokenOptions.foldersOnly,
      includeDescription: tokenOptions.includeDescription,
      autoMeasures: tokenOptions.autoMeasures,
    };

    const collected: AuditVariant[] = [];
    try {
      for (let k = 0; k < variantCount; k++) {
        setVariantProgress({ current: k + 1, total: variantCount });
        setStreamingResponse("");
        setStreamingThinking("");

        const result = await streamSse(
          "/audit",
          {
            csv: stringifyCsv(csvOriginal),
            observation: archivisteObservation,
            model: modelId,
            apiKey,
            baseUrl,
            prep,
            brief: briefMode,
            referencePlan,
            referenceMode,
          },
          {
            onText: (delta) => setStreamingResponse((prev) => prev + delta),
            onReasoning: (delta) => setStreamingThinking((prev) => prev + delta),
            onNotice: (msg) =>
              setStreamingThinking((prev) => `${prev}\n\n> ⟳ ${msg}\n\n`),
          },
          signal,
        );

        if (result.aborted) {
          setLastError("Audit comparatif arrêté par l'utilisateur");
          return;
        }

        collected.push({
          report: (result.done?.report as string) ?? result.text,
          reasoning: result.reasoning,
          plan: (result.done?.plan as string) ?? "",
          notes: (result.done?.notes as string) ?? "",
          usage: result.usage,
          durationMs:
            typeof result.done?.durationMs === "number"
              ? result.done.durationMs
              : null,
          promptVersion:
            typeof result.done?.promptVersion === "string"
              ? result.done.promptVersion
              : null,
        });
      }

      const cmp = await comparePlans(
        collected.map((v) => v.plan),
        signal,
      );
      setAuditVariants(collected);
      setCompareResult(cmp);
    } catch (err) {
      setLastError(formatApiError(err));
    } finally {
      setAuditRunning(false);
      setVariantProgress(null);
    }
  };

  // Adopte une proposition de plan comparée : on la valide comme résultat d'audit
  // (rapport/plan/notes/usage), exactement comme un audit simple — la suite du
  // parcours est inchangée. On vide alors l'état de comparaison.
  const chooseVariant = (k: number) => {
    const v = auditVariants[k];
    if (!v) return;
    setAuditResult(v.report, v.reasoning, v.plan, v.notes);
    setUsageAudit(v.usage);
    setDurationAudit(v.durationMs);
    setPromptVersionAudit(v.promptVersion);
    // Toutes les variantes ont tourné avec le modèle courant.
    setModelAudit(modelId);
    setCompareResult(null);
    setAuditVariants([]);
  };

  const discardComparison = () => {
    setCompareResult(null);
    setAuditVariants([]);
  };

  const stopAudit = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  const downloadReport = () => {
    // Traçabilité : version du prompt ET modèle ayant produit l'audit,
    // consignés en pied d'export, en commentaire HTML — invisibles au rendu
    // Markdown, lisibles dans le fichier.
    const trace = [
      promptVersionAudit ? `prompt AUD-001 v${promptVersionAudit}` : "",
      modelAudit ? `modèle ${modelAudit}` : "",
    ].filter(Boolean);
    const footer = trace.length
      ? `\n\n<!-- ODACEA — ${trace.join(" · ")} -->\n`
      : "";
    const blob = new Blob([rapportAudit + footer], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "rapport_audit.md";
    a.click();
    URL.revokeObjectURL(url);
  };

  const planOk = !!planValide && Object.keys(parsePlanTree(planValide)).length > 0;
  // Un plan adopté sans audit n'a pas de rapport : la vue des résultats
  // s'affiche dès qu'un plan validé existe, quelle que soit son origine.
  const hasResults = !!rapportAudit || !!planValide;
  const planFourni = planOrigin === "fourni";
  // En mode plan seul, le modèle produit surtout le plan, mais accompagne souvent
  // son choix d'un bloc de texte utile (justification, réserves) : dès qu'un tel
  // rapport existe, on l'affiche plutôt que de le masquer derrière l'avertissement.
  const briefSansRapport = briefMode && !rapportAudit.trim();

  // ── Vue de comparaison multi-plans ────────────────────────────────────────
  // Affichée après N audits, tant qu'aucune proposition n'a été adoptée. La
  // comparaison (forme, dossiers communs/propres) est calculée par le moteur.
  if (!hasResults && compareResult && auditVariants.length > 0) {
    const { comparison, variants } = compareResult;
    return (
      <div className="space-y-4">
        <Alert>
          <GitCompare className="h-4 w-4" />
          <AlertTitle>
            Comparaison de {comparison.variantCount} propositions de plan
          </AlertTitle>
          <AlertDescription className="text-xs">
            {comparison.identical
              ? "Les propositions sont structurellement identiques (mêmes dossiers)."
              : `Dossiers : de ${comparison.folderCountRange.min} à ${comparison.folderCountRange.max} · profondeur : de ${comparison.depthRange.min} à ${comparison.depthRange.max} · ${comparison.commonFolderCount} dossier(s) commun(s) à toutes.`}{" "}
            Choisissez la proposition à retenir ; vous pourrez encore l&apos;éditer
            ensuite.
          </AlertDescription>
        </Alert>

        {comparison.commonFolders.length > 0 && (
          <div className="rounded-md border border-(--ink-100) bg-(--paper-50) p-3">
            <p className="text-sm font-medium">
              Dossiers communs à toutes les propositions (
              {comparison.commonFolderCount})
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {comparison.commonFolders.map((f) => (
                <span
                  key={f}
                  className="rounded bg-(--ink-100) px-1.5 py-0.5 text-xs text-(--ink-700)"
                >
                  {f}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          {variants.map((v, k) => (
            <div
              key={v.index}
              className="flex flex-col space-y-2 rounded-md border border-(--ink-100) bg-(--paper-50) p-3"
            >
              <div className="flex items-center justify-between">
                <p className="font-medium">Proposition #{v.index}</p>
                {!v.planExtracted && (
                  <span className="text-xs text-(--danger-600)">
                    plan non exploitable
                  </span>
                )}
              </div>
              <p className="text-xs text-(--ink-500)">
                {v.folders} dossier(s) · profondeur {v.depth} · {v.leaves}{" "}
                feuille(s)
              </p>
              {v.uniqueFolders.length > 0 && (
                <div>
                  <p className="text-xs text-(--ink-500)">
                    Dossiers propres à cette proposition
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {v.uniqueFolders.map((f) => (
                      <span
                        key={f}
                        className="rounded bg-(--accent-100) px-1.5 py-0.5 text-xs text-(--accent-700)"
                      >
                        {f}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <div className="max-h-64 overflow-y-auto rounded border border-(--ink-100) bg-(--paper-0) p-2 text-sm">
                <StreamingMarkdown text={auditVariants[k]?.plan ?? ""} />
              </div>
              <div className="mt-auto pt-1">
                <Button
                  size="sm"
                  className="w-full"
                  onClick={() => chooseVariant(k)}
                  disabled={!v.planExtracted}
                >
                  <Check className="mr-1 h-3.5 w-3.5" />
                  Choisir cette proposition
                </Button>
              </div>
            </div>
          ))}
        </div>

        <StepActions>
          <Button variant="outline" size="lg" onClick={discardComparison}>
            <RotateCcw className="mr-2 h-4 w-4" />
            Revenir au lancement
          </Button>
        </StepActions>
      </div>
    );
  }

// ── Vue de lancement ─────────────────────────────────────────────────────────
  if (!hasResults) {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="obs" className="flex items-center gap-1.5">
            <StickyNote className="h-4 w-4" />
            Note contextuelle de l&apos;archiviste (optionnel)
            <InfoTip label="À propos de la note contextuelle">
              Cette note sera transmise au LLM comme contexte supplémentaire pour
              l&apos;audit.
            </InfoTip>
          </Label>
          <Textarea
            id="obs"
            placeholder="Ex : Ces archives concernent le département RH, période 2015–2022. Attention aux dossiers personnels."
            value={archivisteObservation}
            onChange={(e) => setArchivisteObservation(e.target.value)}
            rows={4}
            disabled={auditRunning}
          />
          {/* Gabarits d'annotation : l'insertion écrit dans le textarea (visible
              et ajustable — jamais d'injection cachée côté système). Désactivé
              tant que le gabarit figure tel quel dans la note ; l'éditer rend
              la main à l'archiviste. Depuis AUD-001 1.1.0, la conservation de
              l'ordre existant est le défaut du prompt : le gabarit est l'opt-out
              (refonte libre). */}
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setArchivisteObservation(
                  appendNoteTemplate(archivisteObservation, REFONTE_LIBRE),
                )
              }
              disabled={
                auditRunning ||
                archivisteObservation.includes(REFONTE_LIBRE)
              }
              title={t.noteTemplates.refonteLibreTitle}
            >
              <ListTree className="mr-1.5 h-3.5 w-3.5" />
              {t.noteTemplates.refonteLibreLabel}
            </Button>
          </div>
        </div>

        <div className="space-y-2 rounded-md border border-(--ink-100) bg-(--paper-50) p-3">
          <Label className="flex items-center gap-1.5">
            <Library className="h-4 w-4" />
            Plan de classement de référence (optionnel)
            <InfoTip label="À propos du plan de classement de référence">
              Importez votre propre plan de classement sous forme d&apos;un
              export Resip ne contenant que des dossiers. Il sera fourni au
              modèle comme contrainte d&apos;audit. Les fichiers éventuellement
              présents sont ignorés.
            </InfoTip>
          </Label>

          {!referencePlan ? (
            <>
              <div
                {...getRefRootProps()}
                data-testid="reference-plan-dropzone"
                className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-md border border-dashed p-4 text-center text-xs transition-colors ${
                  isRefDragActive
                    ? "border-(--accent-500) bg-(--accent-50)"
                    : "border-(--ink-200) hover:border-(--ink-300)"
                } ${auditRunning || refLoading ? "pointer-events-none opacity-60" : ""}`}
              >
                <input {...getRefInputProps()} />
                {refLoading ? (
                  <span className="flex items-center gap-1.5 text-(--ink-500)">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Analyse du CSV…
                  </span>
                ) : (
                  <>
                    <Library className="h-4 w-4 text-(--ink-400)" />
                    <span className="text-(--ink-600)">
                      Déposez un CSV Resip «&nbsp;dossiers seuls&nbsp;» ou
                      cliquez pour le choisir
                    </span>
                  </>
                )}
              </div>

              {/* …ou directement depuis un dossier du poste (comme l'adoption d'un
                  plan) — indisponible en démonstration. */}
              {!DEMO_MODE && (
                <>
                  <p className="text-xs text-(--ink-500)">
                    …ou depuis un dossier existant de votre poste :
                  </p>
                  <PlanFolderPicker
                    disabled={auditRunning || refLoading}
                    onScanned={(res, dir) => {
                      // Le référentiel se stocke comme bloc d'arborescence « nu »
                      // (```text …```), comme la conversion CSV — on retire l'en-tête
                      // Markdown que /plan/from-folder ajoute, pour un affichage et une
                      // injection identiques à l'import CSV.
                      const fence = res.plan.indexOf("```");
                      const tree = fence >= 0 ? res.plan.slice(fence) : res.plan;
                      setReferencePlan(tree, res.rootTitle || dir);
                      setRefFolderCount(res.folderCount);
                      setRefWarnings(res.warnings);
                      setRefErrors([]);
                      setRefServerError(null);
                    }}
                  />
                </>
              )}
            </>
          ) : (
            <>
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-xs text-(--ink-600)">
                  <Check className="h-3.5 w-3.5 text-(--accent-600)" />
                  {referencePlanName || "Plan de référence"} — {refFolderCount}{" "}
                  dossier{refFolderCount > 1 ? "s" : ""}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={clearReference}
                  disabled={auditRunning}
                >
                  Retirer
                </Button>
              </div>
              <pre className="max-h-48 overflow-auto rounded-md border border-(--ink-100) bg-(--paper-0) p-2 text-[11px] leading-snug text-(--ink-700)">
                {referencePlan.replace(/^```text\n?/, "").replace(/\n?```$/, "")}
              </pre>
              <div className="space-y-1.5">
                <Label
                  htmlFor="reference-mode"
                  className="flex items-center gap-1.5 text-xs text-(--ink-500)"
                >
                  Façon d&apos;utiliser ce référentiel
                  <InfoTip label="À propos de la façon d'utiliser le référentiel">
                    «&nbsp;S&apos;en inspirer&nbsp;» garde le plan déduit du vrac
                    en le guidant&nbsp;; «&nbsp;s&apos;y conformer&nbsp;» impose
                    la structure du référentiel.
                  </InfoTip>
                </Label>
                <Select
                  value={referenceMode}
                  onValueChange={setReferenceMode}
                  disabled={auditRunning}
                >
                  <SelectTrigger id="reference-mode" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="inspire">
                      S&apos;en inspirer (indicatif)
                    </SelectItem>
                    <SelectItem value="conform">
                      S&apos;y conformer (prescriptif)
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </>
          )}

          {refErrors.length > 0 && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>CSV de référence invalide</AlertTitle>
              <AlertDescription>
                <ul className="list-disc pl-4">
                  {refErrors.map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          )}
          {refServerError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{refServerError}</AlertDescription>
            </Alert>
          )}
          {refWarnings.length > 0 && (
            <div className="space-y-1 text-xs text-(--ink-500)">
              {refWarnings.map((w, i) => (
                <p key={i} className="flex items-start gap-1.5">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  {w}
                </p>
              ))}
            </div>
          )}
        </div>

        <div className="space-y-1.5 rounded-md border border-(--ink-100) bg-(--paper-50) p-3">
          <div className="flex items-center gap-2">
            <Switch
              id="brief-mode-toggle"
              checked={briefMode}
              onCheckedChange={setBriefMode}
              disabled={auditRunning}
            />
            <Label
              htmlFor="brief-mode-toggle"
              className="flex cursor-pointer items-center gap-1.5 text-sm"
            >
              <FileText className="h-4 w-4" />
              Mode plan seul (sans rapport d&apos;audit)
            </Label>
            <InfoTip label="À propos du mode plan seul">
              Ne demande au modèle que le plan de classement, sans état des lieux
              ni notes. Utile quand l&apos;audit a déjà été fait ou que le vrac
              est bien connu.
            </InfoTip>
          </div>
        </div>

        {/* Audit comparatif multi-plans — demander plusieurs propositions
            de plan et les comparer avant de choisir. */}
        <div className="space-y-1.5 rounded-md border border-(--ink-100) bg-(--paper-50) p-3">
          <Label
            htmlFor="variant-count"
            className="flex items-center gap-1.5"
          >
            <Layers className="h-4 w-4" />
            Propositions de plan à comparer
            <InfoTip label="À propos des propositions de plan à comparer">
              Au-delà de 1, le modèle est relancé autant de fois sur le même vrac
              (chaque exécution est facturée)&nbsp;; les plans obtenus sont
              comparés pour vous aider à choisir.
            </InfoTip>
          </Label>
          <Select
            value={String(variantCount)}
            onValueChange={(v) => setVariantCount(Number(v))}
            disabled={auditRunning}
          >
            <SelectTrigger id="variant-count" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {VARIANT_COUNTS.map((n) => (
                <SelectItem key={n} value={String(n)}>
                  {n === 1
                    ? "1 (audit simple)"
                    : `${n} propositions à comparer`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* ── Workflow parallèle (optionnel) : adopter un plan sans audit ───────
            Mis à part des réglages de l'audit ci-dessus (même traitement visuel
            que « Pour aller plus loin » côté classement) : c'est un chemin
            alternatif — l'archiviste apporte son propre plan, l'audit est
            court-circuité. ─────────────────────────────────────────────── */}
        <Separator />
        <div className="space-y-2">
          <p className="text-xs font-medium tracking-wide text-(--ink-400) uppercase">
            Vous avez déjà un plan&nbsp;?
          </p>
          <p className="flex items-start gap-1.5 text-xs text-(--ink-500)">
            Adoptez-le directement, sans lancer d&apos;audit.
            <InfoTip label="À propos de l'adoption d'un plan">
              Si vous disposez déjà d&apos;un plan de classement, adoptez-le sans
              qu&apos;aucun appel au modèle ne soit fait. Sources : CSV Resip
              «&nbsp;dossiers seuls&nbsp;», plan Markdown exporté d&apos;un projet
              ODACEA, ou un dossier existant de votre poste. Vous pourrez encore le
              modifier avant de continuer.
            </InfoTip>
          </p>
          <div
            {...getImportRootProps()}
            data-testid="import-plan-dropzone"
            className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-md border border-dashed p-4 text-center text-xs transition-colors ${
              isImportDragActive
                ? "border-(--accent-500) bg-(--accent-50)"
                : "border-(--ink-200) hover:border-(--ink-300)"
            } ${auditRunning || importPlanLoading ? "pointer-events-none opacity-60" : ""}`}
          >
            <input {...getImportInputProps()} />
            {importPlanLoading ? (
              <span className="flex items-center gap-1.5 text-(--ink-500)">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Adoption du plan…
              </span>
            ) : (
              <>
                <ClipboardList className="h-4 w-4 text-(--ink-400)" />
                <span className="text-(--ink-600)">
                  Déposez un CSV Resip «&nbsp;dossiers seuls&nbsp;» ou un plan
                  Markdown, ou cliquez pour le choisir
                </span>
              </>
            )}
          </div>

          {/* …ou directement depuis une arborescence de dossiers déjà en place sur
              le poste (indisponible en démonstration). */}
          {!DEMO_MODE && (
            <>
              <p className="text-xs text-(--ink-500)">
                …ou depuis un dossier existant de votre poste :
              </p>
              <PlanFolderPicker
                disabled={auditRunning || importPlanLoading}
                onScanned={(res) => {
                  adoptPlan(res.plan);
                  setImportPlanWarnings(res.warnings);
                  setImportPlanError(null);
                }}
              />
            </>
          )}
          {importPlanError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Plan non exploitable</AlertTitle>
              <AlertDescription className="text-xs whitespace-pre-line">
                {importPlanError}
              </AlertDescription>
            </Alert>
          )}
          {importPlanWarnings.length > 0 && (
            <div className="space-y-1 text-xs text-(--ink-500)">
              {importPlanWarnings.map((w, i) => (
                <p key={i} className="flex items-start gap-1.5">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  {w}
                </p>
              ))}
            </div>
          )}
        </div>

        {lastError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Erreur</AlertTitle>
            <AlertDescription className="text-xs whitespace-pre-line">
              {lastError}
            </AlertDescription>
          </Alert>
        )}

        {auditRunning && (
          <>
            {variantProgress && (
              <p
                role="status"
                aria-live="polite"
                className="text-sm font-medium text-(--ink-700)"
              >
                Proposition {variantProgress.current} / {variantProgress.total}…
              </p>
            )}
            {!streamingThinking && !streamingResponse && (
              <p role="status" aria-live="polite" className="text-sm text-(--ink-500)">
                En attente de la réponse du modèle…
              </p>
            )}
            {streamingThinking && (
              <ThinkingPanel thinking={streamingThinking} defaultOpen />
            )}
            {streamingResponse && (
              <StreamingMarkdown
                text={stripStructureMarkers(streamingResponse)}
              />
            )}
          </>
        )}

        {/* Barre d'actions figée au pied : reste accessible (« Arrêter »)
            pendant que le streaming défile au-dessus. */}
        <StepActions>
          <Button
            onClick={variantCount > 1 ? runComparison : runAudit}
            disabled={auditRunning}
            size="lg"
          >
            {auditRunning ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Audit en cours…
              </>
            ) : variantCount > 1 ? (
              `Comparer ${variantCount} propositions`
            ) : (
              "Lancer l'audit"
            )}
          </Button>
          {auditRunning && (
            <Button onClick={stopAudit} variant="destructiveGhost" size="lg">
              <CircleStop className="mr-2 h-4 w-4" />
              Arrêter
            </Button>
          )}
        </StepActions>
      </div>
    );
  }

  // ── Vue des résultats ───────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      {thinkingAudit && <ThinkingPanel thinking={thinkingAudit} />}

      <Tabs defaultValue={planValide ? "plan" : "rapport"}>
        <TabsList>
          <TabsTrigger value="rapport">
            <BarChart3 className="mr-1.5 h-3.5 w-3.5" />
            Rapport d&apos;audit
          </TabsTrigger>
          <TabsTrigger value="plan">
            <ClipboardList className="mr-1.5 h-3.5 w-3.5" />
            Plan de classement
          </TabsTrigger>
          <TabsTrigger value="notes">
            <Pin className="mr-1.5 h-3.5 w-3.5" />
            Notes
          </TabsTrigger>
        </TabsList>

        <TabsContent value="rapport" className="mt-4 space-y-3">
          {planFourni ? (
            <Alert>
              <Info className="h-4 w-4" />
              <AlertTitle>Plan fourni par l&apos;archiviste</AlertTitle>
              <AlertDescription className="text-xs">
                Ce plan a été adopté directement, sans appel au modèle
                d&apos;audit. Le livrable est dans l&apos;onglet « Plan de
                classement » ; vous pouvez encore le modifier — y compris par
                l&apos;Explorateur Windows.
              </AlertDescription>
            </Alert>
          ) : briefSansRapport ? (
            <Alert>
              <Info className="h-4 w-4" />
              <AlertTitle>Mode plan seul</AlertTitle>
              <AlertDescription className="text-xs">
                Le modèle n&apos;a produit que le plan de classement, sans
                rapport d&apos;audit. Le livrable est
                dans l&apos;onglet « Plan de classement ».
              </AlertDescription>
            </Alert>
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={downloadReport}>
                  <Download className="mr-1 h-3.5 w-3.5" />
                  Exporter en Markdown
                </Button>
                {/* Export PDF imprimable (D6) — rendu par PrintReport (page). */}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => window.print()}
                >
                  <Printer className="mr-1 h-3.5 w-3.5" />
                  Exporter en PDF
                </Button>
              </div>
              <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_220px]">
                <div className="min-w-0">
                  <StreamingMarkdown text={stripStructureMarkers(rapportAudit)} />
                </div>
                <MarkdownToc
                  text={stripStructureMarkers(rapportAudit)}
                  className="order-first sticky top-4 self-start max-h-[calc(100vh-2rem)] overflow-y-auto md:order-last"
                />
              </div>
            </>
          )}
        </TabsContent>

        <TabsContent value="plan" className="mt-4 space-y-3">
          {planValide ? (
            <>
              {planOk ? (
                <Tabs
                  value={planView}
                  onValueChange={(v) => setPlanView(v as PlanView)}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <TabsList>
                      <TabsTrigger value="brut">
                        <FileText className="h-3.5 w-3.5" />
                        Brut
                      </TabsTrigger>
                      <TabsTrigger value="edit">
                        <Pencil className="h-3.5 w-3.5" />
                        Édition
                      </TabsTrigger>
                      <TabsTrigger value="tree">
                        <ListTree className="h-3.5 w-3.5" />
                        Visualisation
                      </TabsTrigger>
                    </TabsList>
                    {planModifie && (
                      <Button variant="outline" size="sm" onClick={resetPlan}>
                        <RotateCcw className="mr-1 h-3.5 w-3.5" />
                        Rétablir le plan de l&apos;IA
                      </Button>
                    )}
                  </div>
                  <TabsContent value="brut" className="mt-3">
                    <StreamingMarkdown text={planValideOriginal || planValide} />
                  </TabsContent>
                  <TabsContent value="tree" className="mt-3">
                    <div className="rounded-md border border-(--ink-100) bg-(--paper-50) p-3">
                      <PlanTree planValide={planValide} />
                    </div>
                  </TabsContent>
                  <TabsContent value="edit" className="mt-3">
                    <div className="rounded-md border border-(--ink-100) bg-(--paper-50) p-3">
                      <PlanTreeEditor
                        planValide={planValide}
                        onChange={setPlanValide}
                      />
                    </div>
                  </TabsContent>
                </Tabs>
              ) : (
                <StreamingMarkdown text={planValide} />
              )}
              {planModifie && (
                <p className="text-xs text-(--ink-500)">
                  Plan modifié par rapport à la proposition de l&apos;IA — la
                  version éditée sera utilisée au classement.
                </p>
              )}

              {/* édition du plan par aller-retour avec l'Explorateur Windows.
                  Masqué en démonstration (endpoints locaux refusés côté serveur). */}
              {planOk && !DEMO_MODE && (
                <div className="rounded-md border border-(--ink-100) bg-(--paper-50) p-3">
                  <PlanExplorerPanel
                    planValide={planValide}
                    onAdopt={setPlanValide}
                  />
                </div>
              )}
            </>
          ) : (
            // Pas de plan : l'avertissement « arborescence technique invalide »
            // en bas de page couvre déjà le cas — inutile de le doubler ici.
            null
          )}
        </TabsContent>

        <TabsContent value="notes" className="mt-4">
          {planNotes ? (
            <StreamingMarkdown text={stripStructureMarkers(planNotes)} />
          ) : planFourni ? (
            <Alert>
              <Info className="h-4 w-4" />
              <AlertDescription className="text-xs">
                Plan fourni sans audit : aucune note pour l&apos;archiviste.
              </AlertDescription>
            </Alert>
          ) : briefMode ? (
            <Alert>
              <Info className="h-4 w-4" />
              <AlertDescription className="text-xs">
                Mode plan seul : aucune note pour l&apos;archiviste n&apos;a été
                demandée.
              </AlertDescription>
            </Alert>
          ) : (
            <Alert variant="warning">
              <AlertDescription>
                Section non détectée dans la réponse.
              </AlertDescription>
            </Alert>
          )}
        </TabsContent>
      </Tabs>

      {!planOk && (
        <Alert variant="warning">
          <AlertTriangle />
          <AlertDescription>
            Ce plan ne contient pas d&apos;arborescence technique valide.
            Relancez l&apos;audit, ou validez le plan pour aller à l&apos;étape
            suivante où vous pourrez le modifier manuellement.
          </AlertDescription>
        </Alert>
      )}

      {/* ── Bottom actions ────────────────────────────────────────────── */}
      <Separator />
      <TokenUsageBar usage={usageAudit} durationMs={durationAudit} label="AUD-001" model={modelAudit} />

      {/* CTA de l'étape + relance. La navigation entre étapes passe par le
          fil d'Ariane. */}
      <StepActions>
        {/* Le Button désactivé porte `pointer-events-none` : on enveloppe d'un
            span pour que le curseur `not-allowed` soit visible au survol. */}
        <span className={!planValide ? "cursor-not-allowed" : undefined}>
          <Button
            size="lg"
            onClick={() => setStep("classement")}
            disabled={!planValide}
          >
            Continuer vers le classement
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </span>
        <IconAction
          label="Relancer l'audit"
          icon={RotateCcw}
          onClick={() => setConfirmReset(true)}
        />
      </StepActions>

      <ConfirmDialog
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title="Relancer l'audit ?"
        description="Le rapport d'audit, le plan de classement extrait et les notes seront supprimés. L'observation contextuelle et le CSV importé sont conservés."
        confirmLabel="Relancer"
        destructive
        onConfirm={resetAudit}
      />
    </div>
  );
}
