"use client";

import { useRef, useState } from "react";
import { useWizard } from "@/lib/store";
import type { LlmClassementRow, SedaRow, ResipResult } from "@/lib/csv/types";
import type { LlmUsage } from "@/lib/llm/client-stream";
import { stringifyCsv } from "@/lib/csv/parse";
import { parsePlanTree } from "@/lib/csv/plan-tree";
import { validateOutputCsv } from "@/lib/csv/validate";
import { REQUIRED_COLUMNS } from "@/lib/csv/constants";
import { streamSse, postJson } from "@/lib/llm/client-stream";
import { TokenUsageBar, sumUsage } from "@/components/token-usage-bar";
import { formatDuration } from "@/lib/tokens/estimate";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { StreamingMarkdown } from "@/components/streaming-markdown";
import { ThinkingPanel } from "@/components/thinking-panel";
import { PlanTree } from "@/components/plan-tree";
import { CsvPreview } from "@/components/csv-preview";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ArborescenceModal } from "@/components/arborescence-modal";
import { IconAction } from "@/components/wizard/icon-action";
import { ApplyPanel } from "@/components/wizard/apply-panel";
import {
  AlertCircle,
  Download,
  RotateCcw,
  Pencil,
  ListTree,
  StickyNote,
  BarChart3,
  Search,
  AlertTriangle,
  FileText,
  XCircle,
  Save,
  Undo2,
  Layers,
  Loader2,
  CircleStop,
  CheckCircle2,
  Circle,
} from "lucide-react";

type BatchState = {
  itemCount: number;
  status: "pending" | "running" | "done" | "error";
  rows: LlmClassementRow[];
  rawText: string;
  thinking?: string;
  /** Estimation live des lignes produites (event `progress`), recalée sur
   *  `rows.length` une fois le lot terminé. */
  liveCount?: number;
  error?: string;
  usage?: LlmUsage | null;
  /** Durée de traitement du lot (ms) renvoyée par l'événement `done`. */
  durationMs?: number | null;
};

export function StepClassement() {
  const {
    csvOriginal,
    planValide,
    planValideOriginal,
    planModifie,
    setPlanValide,
    resetPlan,
    modelId,
    apiKey,
    baseUrl,
    tokenOptions,
    exportOptions,
    classementBatchSize,
    classementRunning,
    setClassementRunning,
    setClassementResult,
    classementBatches,
    setClassementBatches,
    csvFinal,
    thinkingClassement,
    llmRawResponse,
    llmRawRows,
    lastError,
    setLastError,
    usageAudit,
    usageClassementTotal,
    setUsageClassementTotal,
    durationAudit,
    durationClassementTotal,
    setDurationClassementTotal,
  } = useWizard();

  const [streamText, setStreamText] = useState("");
  const [streamThinking, setStreamThinking] = useState("");
  const [planTreeView, setPlanTreeView] = useState(true);
  const [confirmRelaunch, setConfirmRelaunch] = useState(false);
  const [arborescenceOpen, setArborescenceOpen] = useState(false);
  // Progression à l'unité en mode appel-unique (sous le seuil de lots).
  const [singleProgress, setSingleProgress] = useState<{
    done: number;
    total: number;
  } | null>(null);

  // ── État du mode batché ──────────────────────────────────────────────────
  // batchesRef = source de vérité (manipulée dans les boucles async) ;
  // batches = miroir pour le rendu.
  const batchesRef = useRef<BatchState[]>([]);
  const [batches, setBatchesState] = useState<BatchState[] | null>(null);
  const syncBatches = () => setBatchesState([...batchesRef.current]);
  const abortControllerRef = useRef<AbortController | null>(null);

  if (!csvOriginal || !planValide) {
    return (
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>Plan manquant</AlertTitle>
        <AlertDescription>
          Vous devez d&apos;abord lancer un audit.
        </AlertDescription>
      </Alert>
    );
  }

  const folderTree = parsePlanTree(planValide);
  const folderTreeValid = Object.keys(folderTree).length > 0;

  // CSV brut + options de préparation envoyés au backend (qui prépare/classe/convertit).
  const csv = stringifyCsv(csvOriginal);
  const prep = {
    filterColumns: tokenOptions.filterColumns,
    cleanDates: tokenOptions.cleanDates,
    sampleItems: tokenOptions.sampleItems,
    sampleItemsN: tokenOptions.sampleItemsN,
    includeDescription: tokenOptions.includeDescription,
  };

  const runClassement = async () => {
    setStreamText("");
    setStreamThinking("");
    setLastError("");
    setSingleProgress(null);
    batchesRef.current = [];
    setBatchesState(null);
    setClassementBatches(null);

    abortControllerRef.current = new AbortController();

    // Le backend re-dérive les items ; on récupère juste le total pour décider du
    // découpage et afficher les compteurs.
    let total: number;
    try {
      const prepResp = await postJson<{ total: number; error?: string }>(
        "/classement/prepare",
        { csv, prep },
        abortControllerRef.current.signal,
      );
      if (prepResp.error) throw new Error(prepResp.error);
      total = prepResp.total;
    } catch (err) {
      setLastError(err instanceof Error ? err.message : String(err));
      return;
    }

    // Sous le seuil : appel unique, streaming visible.
    if (total <= classementBatchSize) {
      setClassementRunning(true);
      setSingleProgress({ done: 0, total });
      let rawText = "";
      let rawReasoning = "";
      try {
        const result = await streamSse(
          "/classement/batch",
          { csv, planValide, model: modelId, apiKey, baseUrl, prep, batchIndex: 0, batchSize: 0 },
          {
            onText: (delta) => setStreamText((prev) => prev + delta),
            onReasoning: (delta) => setStreamThinking((prev) => prev + delta),
            onProgress: (p) => setSingleProgress({ done: p.itemsDone, total }),
          },
          abortControllerRef.current.signal,
        );
        rawText = result.text;
        rawReasoning = result.reasoning;

        // Interruption par l'utilisateur. Un seul message ; on conserve tout de
        // même la réponse partielle du modèle plutôt que de la perdre.
        if (result.aborted) {
          setLastError("Classement arrêté par l'utilisateur");
          setClassementResult(rawText, rawReasoning, null);
          return;
        }

        const llmRows = (result.done?.llmRows as LlmClassementRow[]) ?? [];
        if (llmRows.length === 0) {
          throw new Error(
            "Aucune ligne CSV n'a pu être extraite de la réponse LLM. Vérifiez le format de sortie.",
          );
        }
        const fin = await postJson<{ resip: ResipResult; error?: string }>(
          "/classement/finalize",
          { csv, planValide, llmRows },
        );
        if (fin.error) throw new Error(fin.error);
        setClassementResult(result.text, result.reasoning, fin.resip, llmRows);
        setUsageClassementTotal(result.usage);
        setDurationClassementTotal(
          typeof result.done?.durationMs === "number" ? result.done.durationMs : null,
        );
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setLastError(msg);
        // Conserve la réponse brute accumulée avant l'erreur (exploitable en
        // diagnostic), même si la conversion RESIP a échoué.
        setClassementResult(rawText, rawReasoning, null);
      } finally {
        setClassementRunning(false);
      }
      return;
    }

    // Au-dessus du seuil : lots successifs (barre de progression).
    const nBatches = Math.ceil(total / classementBatchSize);
    batchesRef.current = Array.from({ length: nBatches }, (_, i) => ({
      itemCount: Math.min(classementBatchSize, total - i * classementBatchSize),
      status: "pending" as const,
      rows: [],
      rawText: "",
    }));
    syncBatches();

    setClassementRunning(true);
    for (let i = 0; i < batchesRef.current.length; i++) {
      if (abortControllerRef.current.signal.aborted) break;
      await runSingleBatch(i);
    }
    setClassementRunning(false);
    if (batchesRef.current.every((b) => b.status === "done")) await finalize();
  };

  const runSingleBatch = async (i: number) => {
    const b = batchesRef.current[i];
    b.status = "running";
    b.error = undefined;
    b.rawText = "";
    b.thinking = "";
    b.liveCount = 0;
    syncBatches();
    try {
      const result = await streamSse(
        "/classement/batch",
        {
          csv,
          planValide,
          model: modelId,
          apiKey,
          baseUrl,
          prep,
          batchIndex: i,
          batchSize: classementBatchSize,
        },
        {
          onText: (delta) => {
            b.rawText += delta;
            syncBatches();
          },
          onReasoning: (delta) => {
            b.thinking = (b.thinking ?? "") + delta;
            syncBatches();
          },
          onProgress: (p) => {
            b.liveCount = p.itemsDone;
            syncBatches();
          },
        },
        abortControllerRef.current?.signal,
      );

      // Interruption par l'utilisateur : on marque le lot en erreur mais on
      // conserve le texte brut déjà streamé (visible dans le volet du lot).
      if (result.aborted) {
        b.rawText = result.text || b.rawText;
        b.status = "error";
        b.error = "Lot arrêté par l'utilisateur";
        syncBatches();
        return;
      }

      const rows = (result.done?.llmRows as LlmClassementRow[]) ?? [];
      if (rows.length === 0) {
        throw new Error(
          "Aucune ligne CSV n'a pu être extraite de la réponse pour ce lot.",
        );
      }
      b.rows = rows;
      b.rawText = result.text;
      b.usage = result.usage;
      b.durationMs =
        typeof result.done?.durationMs === "number" ? result.done.durationMs : null;
      b.status = "done";
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      b.status = "error";
      b.error = msg;
    }
    syncBatches();
  };

  const finalize = async () => {
    const all = batchesRef.current.flatMap((b) => b.rows);
    const joinedRaw = batchesRef.current.map((b) => b.rawText).join("\n\n");
    // Résumé léger persisté avec le projet (sans le texte brut, déjà dans
    // llmRawResponse) : conserve la trace du mode lot après rechargement.
    const summary = batchesRef.current.map((b) => ({
      itemCount: b.itemCount,
      rows: b.rows,
    }));
    setClassementBatches(summary);
    setUsageClassementTotal(sumUsage(batchesRef.current.map((b) => b.usage)));
    // Durée totale du classement = somme des durées de lot (le traitement est
    // séquentiel). null si aucun lot n'a remonté de durée.
    const totalDuration = batchesRef.current.reduce(
      (acc, b) => acc + (b.durationMs ?? 0),
      0,
    );
    setDurationClassementTotal(totalDuration > 0 ? totalDuration : null);
    // Conversion RESIP en une seule passe sur l'ensemble des lots (backend).
    try {
      const fin = await postJson<{ resip: ResipResult; error?: string }>(
        "/classement/finalize",
        { csv, planValide, llmRows: all },
      );
      if (fin.error) throw new Error(fin.error);
      setClassementResult(joinedRaw, "", fin.resip, all);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setLastError(msg);
      setClassementResult(joinedRaw, "", null, all);
    }
  };

  const retryBatch = async (i: number) => {
    // Contrôleur neuf : l'ancien peut être resté `aborted` après un « Arrêter »,
    // ce qui ferait échouer la relance instantanément.
    abortControllerRef.current = new AbortController();
    setClassementRunning(true);
    await runSingleBatch(i);
    setClassementRunning(false);
    if (batchesRef.current.every((b) => b.status === "done")) await finalize();
  };

  const retryAllErrored = async () => {
    abortControllerRef.current = new AbortController();
    setClassementRunning(true);
    for (let i = 0; i < batchesRef.current.length; i++) {
      if (abortControllerRef.current.signal.aborted) break;
      if (batchesRef.current[i].status === "error") await runSingleBatch(i);
    }
    setClassementRunning(false);
    if (batchesRef.current.every((b) => b.status === "done")) await finalize();
  };

  const clearBatches = () => {
    batchesRef.current = [];
    setBatchesState(null);
    setClassementBatches(null);
  };

  const stopClassement = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  const timestamp = () =>
    new Date()
      .toISOString()
      .replace("T", "_")
      .replace(/-/g, "")
      .replace(/:/g, "")
      .slice(0, 15);

  // Mise en forme des titres au moment du téléchargement (cf. options d'export
  // dans les Paramètres). Deux transformations indépendantes :
  //  - folderTitleFromFile : pour les dossiers (RecordGrp), remplace le
  //    Content.Title hiérarchique par le nom technique de l'arborescence (File) ;
  //    la racine (File === ".") n'est pas touchée.
  //  - keepOriginalFileTitle : pour les fichiers (Item), rétablit le titre
  //    d'origine du CSV importé (indexé par chemin File) à la place du renommage
  //    proposé par l'IA.
  const applyExportTitleChoices = (rows: SedaRow[]): SedaRow[] => {
    const { folderTitleFromFile, keepOriginalFileTitle } = exportOptions;
    if (!folderTitleFromFile && !keepOriginalFileTitle) return rows;

    const origItemTitle = new Map<string, string>();
    if (keepOriginalFileTitle && csvOriginal) {
      for (const r of csvOriginal) {
        if (r["Content.DescriptionLevel"] === "Item")
          origItemTitle.set(r["File"], r["Content.Title"] ?? "");
      }
    }

    return rows.map((r) => {
      const level = r["Content.DescriptionLevel"];
      if (
        folderTitleFromFile &&
        level === "RecordGrp" &&
        r["File"] &&
        r["File"] !== "."
      )
        return { ...r, "Content.Title": r["File"] };
      if (keepOriginalFileTitle && level === "Item") {
        const orig = origItemTitle.get(r["File"]);
        if (orig) return { ...r, "Content.Title": orig };
      }
      return r;
    });
  };

  const downloadCsv = () => {
    if (!csvFinal) return;
    const csv = stringifyCsv(applyExportTitleChoices(csvFinal.rows), csvFinal.columns);
    // Pas de BOM : Resip rejette le header avec BOM (le ﻿ se colle à "ID")
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `classement_final_${timestamp()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadRowsCsv = (
    rows: LlmClassementRow[] | null,
    suffix: string,
  ) => {
    if (!rows || rows.length === 0) return;
    const csv = stringifyCsv(rows as unknown as Record<string, string>[]);
    const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `classement_llm_brut${suffix}_${timestamp()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const downloadRawLlmCsv = () => downloadRowsCsv(llmRawRows, "");

  const preCsvText = llmRawResponse.includes("```csv")
    ? llmRawResponse.split("```csv")[0].trim()
    : "";

  // ── Mesures ─────────────────────────────────────────────────────────────────
  const itemRowsOrig = csvOriginal.filter(
    (r) => r["Content.DescriptionLevel"] === "Item",
  );
  const nOrigItems = itemRowsOrig.length;
  const nNewRg = csvFinal
    ? csvFinal.rows.filter(
        (r) => r["Content.DescriptionLevel"] === "RecordGrp",
      ).length
    : 0;
  const nNewItems = csvFinal
    ? csvFinal.rows.filter((r) => r["Content.DescriptionLevel"] === "Item")
        .length
    : 0;
  const nNoDate = csvFinal
    ? csvFinal.rows.filter(
        (r) =>
          r["Content.DescriptionLevel"] === "Item" &&
          (!r["Content.StartDate"] || r["Content.StartDate"] === ""),
      ).length
    : 0;
  const missing = nOrigItems - nNewItems;
  const convWarnings = csvFinal?.warnings ?? [];
  const nUnknownTarget = convWarnings.filter((w) =>
    w.startsWith("TargetFolder inconnu"),
  ).length;
  const nAbsentLlm = convWarnings.filter((w) =>
    w.startsWith("Fichier non classé"),
  ).length;
  let nExtFixed = 0;
  for (const w of convWarnings) {
    if (w.includes("NewTitle(s) corrigé(s)")) {
      const m = w.match(/^(\d+)/);
      if (m) nExtFixed = parseInt(m[1], 10);
      break;
    }
  }

  // Conformité au plan : calculée à la source (backend) — on l'affiche telle
  // quelle. `stats` est absent des projets persistés avant son introduction
  // (→ relancer le classement pour obtenir l'indicateur).
  const stats = csvFinal?.stats;
  const planEcarts = stats
    ? stats.foldersOffPlan.length + stats.foldersMissing.length
    : 0;

  const csvFinalCols = csvFinal ? Object.keys(csvFinal.rows[0] ?? {}) : [];
  const missingCols = csvFinal
    ? REQUIRED_COLUMNS.filter((c) => !csvFinalCols.includes(c))
    : [];
  const coherenceErrors = csvFinal ? validateOutputCsv(csvFinal.rows) : [];

  return (
    <div className="space-y-4">
      {/* ── Plan summary ──────────────────────────────────────────────── */}
      {planModifie && (
        <Alert>
          <AlertDescription>
            Plan de classement validé et revu par l&apos;utilisateur
          </AlertDescription>
        </Alert>
      )}

      <Accordion type="single" collapsible>
        <AccordionItem value="plan">
          <AccordionTrigger>
            <span className="flex items-center gap-1.5">
              <Pencil className="h-3.5 w-3.5" />
              Consulter / modifier le plan validé à l&apos;étape précédente
            </span>
          </AccordionTrigger>
          <AccordionContent>
            <div className="space-y-3 pt-2">
              {folderTreeValid && (
                <div className="flex items-center gap-2">
                  <Switch
                    id="plan-tree-toggle-cla"
                    checked={planTreeView}
                    onCheckedChange={setPlanTreeView}
                  />
                  <Label
                    htmlFor="plan-tree-toggle-cla"
                    className="flex cursor-pointer items-center gap-1.5 text-sm"
                  >
                    <ListTree className="h-3.5 w-3.5" />
                    Vue arborescence
                  </Label>
                </div>
              )}
              {folderTreeValid && planTreeView ? (
                <PlanTree planValide={planValide} />
              ) : (
                <PlanEditor
                  planValide={planValide}
                  planModifie={planModifie}
                  onSave={(v) => setPlanValide(v)}
                  onRevert={() => {
                    setPlanValide(planValideOriginal);
                    resetPlan();
                  }}
                />
              )}
            </div>
          </AccordionContent>
        </AccordionItem>
      </Accordion>

      <Separator />

      {/* ── Launch or results ─────────────────────────────────────────── */}
      {csvFinal === null ? (
        <LaunchSection
          folderTreeValid={folderTreeValid}
          classementRunning={classementRunning}
          lastError={lastError}
          llmRawResponse={llmRawResponse}
          streamThinking={streamThinking}
          streamText={streamText}
          batches={batches}
          singleProgress={singleProgress}
          onRun={runClassement}
          onStop={stopClassement}
          onRetryBatch={retryBatch}
          onRetryAll={retryAllErrored}
        />
      ) : missingCols.length > 0 ? (
        <>
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>
              Le CSV produit par le LLM ne respecte pas le format SEDA attendu
            </AlertTitle>
            <AlertDescription>
              <p className="text-sm">
                <strong>Colonnes manquantes :</strong> {missingCols.join(", ")}
              </p>
              <p className="mt-1 text-sm">
                <strong>Colonnes reçues :</strong>{" "}
                {Object.keys(csvFinal!.rows[0] ?? {}).join(", ")}
              </p>
              <p className="mt-2 text-sm">
                Le modèle n&apos;a pas suivi les instructions. Relancez le
                classement ou utilisez un modèle plus performant.
              </p>
              {llmRawResponse && (
                <Accordion type="single" collapsible className="mt-2">
                  <AccordionItem value="raw">
                    <AccordionTrigger>
                      <span className="flex items-center gap-1.5">
                        <FileText className="h-3.5 w-3.5" />
                        Réponse brute du LLM (diagnostic)
                      </span>
                    </AccordionTrigger>
                    <AccordionContent>
                      <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded border border-(--ink-100) bg-(--paper-100) p-2 font-mono text-xs text-(--ink-700)">
                        {llmRawResponse.slice(0, 3000)}
                        {llmRawResponse.length > 3000 ? "…" : ""}
                      </pre>
                    </AccordionContent>
                  </AccordionItem>
                </Accordion>
              )}
            </AlertDescription>
          </Alert>
          <div className="flex justify-center">
            <Button
              variant="outline"
              size="lg"
              onClick={() => setConfirmRelaunch(true)}
            >
              <RotateCcw className="mr-2 h-4 w-4" />
              Relancer le classement
            </Button>
          </div>
        </>
      ) : (
        <>
          {classementBatches && (
            <Alert>
              <Layers className="h-4 w-4" />
              <AlertTitle>Classement produit par lots</AlertTitle>
              <AlertDescription>
                Ce classement a été produit en{" "}
                <strong>{classementBatches.length} lot(s)</strong> traités
                successivement, puis fusionnés dans l&apos;ordre d&apos;origine
                et convertis en une seule passe — garantissant la cohérence de
                l&apos;ensemble (dossiers, identifiants et dates calculés sur la
                totalité).
              </AlertDescription>
            </Alert>
          )}

          {thinkingClassement && <ThinkingPanel thinking={thinkingClassement} />}

          {preCsvText && (
            <Accordion type="single" collapsible>
              <AccordionItem value="demarche">
                <AccordionTrigger>
                  <span className="flex items-center gap-1.5">
                    <StickyNote className="h-3.5 w-3.5" />
                    Démarche de l&apos;IA
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="pt-2">
                    <StreamingMarkdown text={preCsvText} />
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}

          <h3 className="flex items-center gap-2 text-lg font-semibold text-(--ink-900)">
            <BarChart3 className="h-4 w-4" />
            Rapport de couverture
          </h3>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <Metric label="Dossiers créés" value={nNewRg} />
            <Metric
              label="Items classés"
              value={`${nNewItems} / ${nOrigItems}`}
              delta={missing > 0 ? `-${missing} non classé(s)` : undefined}
              deltaKind="bad"
            />
            <Metric
              label="Sans date"
              value={nNoDate}
              delta={nNoDate > 0 ? "À compléter" : undefined}
              deltaKind="bad"
            />
            <Metric
              label="Extensions corrigées"
              value={nExtFixed}
              delta={nExtFixed > 0 ? "Vérifier" : undefined}
              deltaKind="bad"
            />
            <Metric
              label="Respect du plan"
              value={
                !stats
                  ? "—"
                  : !stats.planParsed
                    ? "—"
                    : stats.planMatches
                      ? "Conforme"
                      : `${planEcarts} écart(s)`
              }
              delta={
                !stats
                  ? "Relancer le classement"
                  : !stats.planParsed
                    ? "Arborescence du plan illisible"
                    : stats.planMatches
                      ? "Identique au plan d'audit"
                      : `${stats.foldersOffPlan.length} hors plan · ${stats.foldersMissing.length} manquant(s)`
              }
              deltaKind={stats?.planMatches ? "good" : "bad"}
            />
          </div>

          {stats &&
            stats.planParsed &&
            (!stats.planMatches || stats.itemsMalformed > 0) && (
              <Alert variant="warning">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>L&apos;arborescence du classement diffère du plan d&apos;audit</AlertTitle>
                <AlertDescription className="space-y-1 text-sm">
                  {stats.foldersOffPlan.length > 0 && (
                    <p className="mb-0!">
                      <strong>Dossiers hors plan</strong> (inventés au classement) :{" "}
                      {stats.foldersOffPlan.join(", ")}
                    </p>
                  )}
                  {stats.foldersMissing.length > 0 && (
                    <p className="mb-0!">
                      <strong>Dossiers du plan non réalisés</strong> (aucun contenu) :{" "}
                      {stats.foldersMissing.join(", ")}
                    </p>
                  )}
                  {stats.itemsMalformed > 0 && (
                    <p className="mb-0!">
                      <strong>{stats.itemsMalformed} fichier(s) à cible malformée</strong>{" "}
                      (le modèle a indiqué un nom de fichier au lieu d&apos;un
                      dossier) rattaché(s) à la racine. Voir les avertissements de
                      conversion pour plus de détails.
                    </p>
                  )}
                </AlertDescription>
              </Alert>
            )}

          {missing > 0 && (nAbsentLlm > 0 || nUnknownTarget > 0) && (
            <p className="text-xs text-(--ink-500)">
              Détail des non classés :{" "}
              {[
                nAbsentLlm > 0
                  ? `${nAbsentLlm} absent(s) de la sortie LLM`
                  : null,
                nUnknownTarget > 0
                  ? `${nUnknownTarget} avec dossier cible inconnu`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          )}

          {nNoDate > 0 && (
            <Alert variant="warning">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>
                {nNoDate} Item(s) sans date. Vérifiez les champs
                StartDate/EndDate dans le CSV final.
              </AlertDescription>
            </Alert>
          )}

          {coherenceErrors.length > 0 && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Problèmes de cohérence détectés</AlertTitle>
              <AlertDescription>
                <ul className="list-inside list-disc text-sm">
                  {coherenceErrors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          )}

          {convWarnings.length > 0 && (
            <Accordion type="single" collapsible>
              <AccordionItem value="warns">
                <AccordionTrigger>
                  <span className="flex items-center gap-1.5">
                    <AlertTriangle className="h-3.5 w-3.5 text-(--warning-500)" />
                    {convWarnings.length} avertissement(s) de conversion
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <ul className="list-inside list-disc space-y-1 pt-2 text-xs text-(--ink-700)">
                    {convWarnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}

          <Separator />

          <div className="space-y-2">
            <h3 className="text-lg font-semibold text-(--ink-900)">
              Aperçu du CSV final
            </h3>
            <p className="text-xs text-(--ink-500)">
              {csvFinal.rows.length} lignes · {csvFinal.columns.length} colonnes
            </p>
            <CsvPreview rows={applyExportTitleChoices(csvFinal.rows)} maxRows={20} />
          </div>

          <Separator />

          {llmRawRows && llmRawRows.length > 0 && (
            <Accordion type="single" collapsible>
              <AccordionItem value="debug">
                <AccordionTrigger>
                  <span className="flex items-center gap-1.5">
                    <Search className="h-3.5 w-3.5" />
                    {classementBatches
                      ? `CSV brut de l'IA par lot (${classementBatches.length})`
                      : "CSV brut de l'IA (avant conversion)"}
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  {classementBatches ? (
                    <div className="space-y-3 pt-2">
                      <Alert>
                        <Layers className="h-4 w-4" />
                        <AlertTitle>Cohérence entre les lots</AlertTitle>
                        <AlertDescription className="text-xs">
                          Chaque lot a été classé avec le{" "}
                          <strong>même plan validé</strong> (mêmes dossiers
                          cibles). Les lignes de tous les lots sont ensuite
                          fusionnées dans l&apos;ordre d&apos;origine puis
                          converties <strong>en une seule passe</strong> :
                          dédoublonnage des dossiers, attribution des
                          identifiants et calcul des dates portent sur la
                          totalité — il ne peut donc pas y avoir de doublon ni de
                          collision d&apos;identifiants entre lots. Les tableaux
                          ci-dessous montrent ce que l&apos;IA a produit pour
                          chaque tranche.
                        </AlertDescription>
                      </Alert>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={downloadRawLlmCsv}
                      >
                        <Download className="mr-1 h-3.5 w-3.5" />
                        Télécharger le CSV brut complet ({llmRawRows.length}{" "}
                        lignes)
                      </Button>
                      {classementBatches.map((b, i) => (
                        <div
                          key={i}
                          className="space-y-1.5 rounded-md border border-(--ink-100) p-2"
                        >
                          <p className="text-xs font-medium text-(--ink-700)">
                            Lot {i + 1} / {classementBatches.length} —{" "}
                            {b.itemCount} item(s) envoyé(s) · {b.rows.length}{" "}
                            ligne(s) produite(s)
                          </p>
                          {b.rows.length > 0 ? (
                            <>
                              <CsvPreview
                                rows={
                                  b.rows as unknown as Record<string, string>[]
                                }
                                maxRows={10}
                              />
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() =>
                                  downloadRowsCsv(b.rows, `_lot${i + 1}`)
                                }
                              >
                                <Download className="mr-1 h-3.5 w-3.5" />
                                Télécharger ce lot
                              </Button>
                            </>
                          ) : (
                            <p className="text-xs text-(--ink-500)">
                              Aucune ligne produite pour ce lot.
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="space-y-2 pt-2">
                      <CsvPreview
                        rows={llmRawRows as unknown as Record<string, string>[]}
                        maxRows={20}
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={downloadRawLlmCsv}
                      >
                        <Download className="mr-1 h-3.5 w-3.5" />
                        Télécharger le CSV brut IA
                      </Button>
                    </div>
                  )}
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}

          {(usageClassementTotal ||
            usageAudit ||
            durationClassementTotal ||
            durationAudit) && (
            <div className="space-y-0.5">
              <TokenUsageBar usage={usageClassementTotal} durationMs={durationClassementTotal} label="CLA-001" />
              {((usageAudit && usageClassementTotal) || (durationAudit && durationClassementTotal)) && (
                <p className="text-xs font-medium text-(--ink-500)">
                  {(() => {
                    const segments: string[] = [];
                    if (usageAudit && usageClassementTotal) {
                      const total = sumUsage([usageAudit, usageClassementTotal]);
                      if (total?.totalTokens)
                        segments.push(`${(total.totalTokens / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} k tokens`);
                    }
                    if (durationAudit && durationClassementTotal)
                      segments.push(`traité en ${formatDuration(durationAudit + durationClassementTotal)}`);
                    return `Total session — ${segments.join(". ")}`;
                  })()}
                </p>
              )}
            </div>
          )}

          {/* CTA de l'étape + relance. La navigation entre étapes passe par le
              fil d'Ariane ; la remise à zéro par « Nouveau projet » (sidebar). */}
          <Separator />
          <div className="flex items-center justify-center gap-2">
            <Button onClick={downloadCsv} size="lg">
              <Download className="mr-2 h-4 w-4" />
              Télécharger le CSV final
            </Button>
            <Button
              variant="outline"
              onClick={() => setArborescenceOpen(true)}
            >
              <ListTree className="mr-2 h-4 w-4" />
              Arborescence
            </Button>
            <IconAction
              label="Relancer le classement"
              icon={RotateCcw}
              onClick={() => setConfirmRelaunch(true)}
            />
          </div>

          {csvFinal.rows.length > 0 && (
            <>
              <Separator />
              <ApplyPanel rows={applyExportTitleChoices(csvFinal.rows)} />
            </>
          )}
        </>
      )}

      <ConfirmDialog
        open={confirmRelaunch}
        onOpenChange={setConfirmRelaunch}
        title="Relancer le classement ?"
        description="Le classement actuel (réponse LLM brute et CSV final) sera supprimé. Le plan validé, l'audit et le CSV importé sont conservés."
        confirmLabel="Relancer"
        destructive
        onConfirm={() => {
          clearBatches();
          setClassementResult("", "", null, null);
        }}
      />

      {csvFinal && (
        <ArborescenceModal
          open={arborescenceOpen}
          onOpenChange={setArborescenceOpen}
          csvOriginal={csvOriginal}
          csvFinal={csvFinal}
        />
      )}
    </div>
  );
}

function LaunchSection({
  folderTreeValid,
  classementRunning,
  lastError,
  llmRawResponse,
  streamThinking,
  streamText,
  batches,
  singleProgress,
  onRun,
  onStop,
  onRetryBatch,
  onRetryAll,
}: {
  folderTreeValid: boolean;
  classementRunning: boolean;
  lastError: string;
  llmRawResponse: string;
  streamThinking: string;
  streamText: string;
  batches: BatchState[] | null;
  singleProgress: { done: number; total: number } | null;
  onRun: () => void;
  onStop: () => void;
  onRetryBatch: (i: number) => void;
  onRetryAll: () => void;
}) {
  const isBatched = batches !== null;
  const total = batches?.length ?? 0; // nombre de lots (en-têtes de volets)
  const erroredIdx =
    batches?.flatMap((b, i) => (b.status === "error" ? [i] : [])) ?? [];
  // Progression à l'unité : lots terminés → compte réel (rows.length), lot en
  // cours → estimation live (liveCount), lots en attente → 0.
  const totalItems = batches?.reduce((s, b) => s + b.itemCount, 0) ?? 0;
  const itemsDone =
    batches?.reduce(
      (s, b) =>
        s + (b.status === "done" ? b.rows.length : b.liveCount ?? 0),
      0,
    ) ?? 0;

  // Accordéon contrôlé : suit automatiquement le lot en cours (ouverture au
  // démarrage du lot, fermeture quand il termine et que le suivant démarre).
  // L'utilisateur peut toujours déplier manuellement un lot terminé.
  const runningIdx = batches?.findIndex((b) => b.status === "running") ?? -1;
  const [openBatch, setOpenBatch] = useState<string | undefined>(undefined);
  // Ajuste l'état pendant le rendu (pattern React) plutôt que dans un effet :
  // quand un nouveau lot démarre, on l'ouvre ; l'utilisateur garde la main.
  const [prevRunning, setPrevRunning] = useState(runningIdx);
  if (runningIdx !== prevRunning) {
    setPrevRunning(runningIdx);
    if (runningIdx >= 0) setOpenBatch(`batch-${runningIdx}`);
  }

  if (!folderTreeValid) {
    return (
      <Alert variant="destructive">
        <XCircle className="h-4 w-4" />
        <AlertTitle>Arborescence technique invalide</AlertTitle>
        <AlertDescription>
          Arborescence technique absente ou invalide. Retournez à
          l&apos;audit pour relancer, ou corrigez le plan dans le panneau
          ci-dessus.
        </AlertDescription>
      </Alert>
    );
  }

  return (
    <div className="space-y-3">
      <Alert>
        <AlertDescription>
          Le classement va reclasser virtuellement chaque fichier selon le plan
          validé et produire un CSV SEDA restructuré. Cette étape peut prendre
          plusieurs minutes selon la taille du vrac.
        </AlertDescription>
      </Alert>

      {lastError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Erreur</AlertTitle>
          <AlertDescription>
            <p className="text-xs">{lastError}</p>
            {llmRawResponse && (
              <Accordion type="single" collapsible className="mt-2">
                <AccordionItem value="raw">
                  <AccordionTrigger>
                    <span className="flex items-center gap-1.5">
                      <FileText className="h-3.5 w-3.5" />
                      Réponse brute du LLM (diagnostic)
                    </span>
                  </AccordionTrigger>
                  <AccordionContent>
                    <p className="text-xs text-(--ink-500)">
                      Le LLM a bien répondu, mais sa sortie n&apos;a pas pu être
                      convertie en CSV RESIP. Vérifiez ci-dessous si le travail
                      est exploitable, sinon relancez.
                    </p>
                    <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded border border-(--ink-100) bg-(--paper-100) p-2 font-mono text-xs text-(--ink-700)">
                      {llmRawResponse.slice(0, 5000)}
                      {llmRawResponse.length > 5000 ? "…" : ""}
                    </pre>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            )}
          </AlertDescription>
        </Alert>
      )}

      {isBatched ? (
        <div className="space-y-3">
          <Alert>
            <Layers className="h-4 w-4" />
            <AlertTitle>Mode traitement par lot activé</AlertTitle>
            <AlertDescription>
              Le nombre d&apos;items dépasse le seuil configuré : le classement
              est découpé en <strong>{total} lot(s)</strong> traités
              successivement. Chaque lot reçoit le plan validé complet ; les
              résultats sont ensuite fusionnés et convertis en une seule passe
              pour garantir un classement cohérent sur l&apos;ensemble.
            </AlertDescription>
          </Alert>
          <ItemProgressBar done={itemsDone} total={totalItems} />

          {/* Un volet par lot : se déplie automatiquement pendant le traitement
              (streaming live), se replie une fois terminé. */}
          <Accordion
            type="single"
            collapsible
            value={openBatch}
            onValueChange={setOpenBatch}
          >
            {batches!.map((b, i) => (
              <AccordionItem value={`batch-${i}`} key={i}>
                <AccordionTrigger>
                  <span className="flex items-center gap-2">
                    <BatchStatusIcon status={b.status} />
                    <span>
                      Lot {i + 1} / {total} — {b.itemCount} item(s)
                      {b.status === "done" &&
                        ` · ${b.rows.length} ligne(s) produite(s)`}
                      {b.status === "running" && " · en cours…"}
                      {b.status === "error" && " · erreur"}
                    </span>
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-2 pt-1">
                    {b.status === "error" && b.error && (
                      <p className="text-xs text-(--danger-500)">{b.error}</p>
                    )}
                    {b.thinking && (
                      <ThinkingPanel thinking={b.thinking} defaultOpen />
                    )}
                    {b.rawText ? (
                      <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md border border-(--ink-100) bg-(--paper-100) p-3 font-mono text-xs text-(--ink-700)">
                        {b.rawText}
                      </pre>
                    ) : (
                      b.status !== "error" && (
                        <p className="text-sm text-(--ink-500)">
                          {b.status === "running"
                            ? "En attente de la réponse du modèle…"
                            : "Lot en attente de traitement."}
                        </p>
                      )
                    )}
                  </div>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>

          {erroredIdx.length > 0 && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>{erroredIdx.length} lot(s) en erreur</AlertTitle>
              <AlertDescription>
                <ul className="space-y-1.5 text-xs">
                  {erroredIdx.map((i) => (
                    <li
                      key={i}
                      className="flex items-center justify-between gap-2"
                    >
                      <span>
                        Lot {i + 1} : {batches![i].error}
                      </span>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={classementRunning}
                        onClick={() => onRetryBatch(i)}
                      >
                        <RotateCcw className="mr-1 h-3.5 w-3.5" />
                        Relancer ce lot
                      </Button>
                    </li>
                  ))}
                </ul>
                {erroredIdx.length > 1 && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-2 w-full"
                    disabled={classementRunning}
                    onClick={onRetryAll}
                  >
                    <RotateCcw className="mr-1 h-3.5 w-3.5" />
                    Relancer tous les lots en erreur
                  </Button>
                )}
              </AlertDescription>
            </Alert>
          )}
        </div>
      ) : (
        classementRunning && (
          <>
            {singleProgress && (
              <ItemProgressBar
                done={singleProgress.done}
                total={singleProgress.total}
              />
            )}
            {!streamThinking && !streamText && (
              <p className="text-sm text-(--ink-500)">
                En attente de la réponse du modèle…
              </p>
            )}
            {streamThinking && (
              <ThinkingPanel thinking={streamThinking} defaultOpen />
            )}
            {streamText && (
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md border border-(--ink-100) bg-(--paper-100) p-3 font-mono text-xs text-(--ink-700)">
                {streamText}
              </pre>
            )}
          </>
        )
      )}

      <div className="flex items-center justify-center gap-2">
        <Button onClick={onRun} disabled={classementRunning} size="lg">
          {classementRunning ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Classement en cours…
            </>
          ) : (
            "Lancer le classement"
          )}
        </Button>
        {classementRunning && (
          <Button onClick={onStop} variant="destructiveGhost" size="lg">
            <CircleStop className="mr-2 h-4 w-4" />
            Arrêter
          </Button>
        )}
      </div>
    </div>
  );
}

function PlanEditor({
  planValide,
  planModifie,
  onSave,
  onRevert,
}: {
  planValide: string;
  planModifie: boolean;
  onSave: (v: string) => void;
  onRevert: () => void;
}) {
  const [draft, setDraft] = useState(planValide);

  return (
    <div className="space-y-3">
      <Textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={20}
        className="font-mono text-xs"
      />
      <div className="grid grid-cols-2 gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onSave(draft)}
          disabled={draft.trim() === planValide.trim()}
        >
          <Save className="mr-1.5 h-3.5 w-3.5" />
          Enregistrer les modifications
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={onRevert}
          disabled={!planModifie}
        >
          <Undo2 className="mr-1.5 h-3.5 w-3.5" />
          Rétablir le plan de l&apos;IA
        </Button>
      </div>
    </div>
  );
}

function ItemProgressBar({ done, total }: { done: number; total: number }) {
  // Estimation live : bornée à [0, total]. Le compte affiché est plafonné au
  // total (le LLM peut produire plus de lignes que d'items en cours de flux).
  const shown = Math.min(done, total);
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-(--ink-500)">
        <span>
          {shown} / {total} fichier(s) classé(s)
        </span>
        <span>{pct}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-(--ink-100)">
        <div
          className="h-full bg-(--ink-700) transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function BatchStatusIcon({ status }: { status: BatchState["status"] }) {
  switch (status) {
    case "running":
      return <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-(--ink-700)" />;
    case "done":
      return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-(--success-500)" />;
    case "error":
      return <AlertCircle className="h-3.5 w-3.5 shrink-0 text-(--danger-500)" />;
    default:
      return <Circle className="h-3.5 w-3.5 shrink-0 text-(--ink-300)" />;
  }
}

function Metric({
  label,
  value,
  delta,
  deltaKind,
}: {
  label: string;
  value: number | string;
  delta?: string;
  deltaKind?: "good" | "bad";
}) {
  return (
    <div className="rounded-md border border-(--ink-100) bg-(--paper-50) p-3">
      <div className="text-xs text-(--ink-500)">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-(--ink-900)">{value}</div>
      {delta && (
        <div
          className={
            "mt-0.5 text-xs " +
            (deltaKind === "bad" ? "text-(--danger-500)" : "text-(--success-500)")
          }
        >
          {delta}
        </div>
      )}
    </div>
  );
}
