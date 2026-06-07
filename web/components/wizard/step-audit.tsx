"use client";

import { useState, useRef } from "react";
import { useWizard } from "@/lib/store";
import { stringifyCsv } from "@/lib/csv/parse";
import { stripStructureMarkers } from "@/lib/csv/extract";
import { parsePlanTree } from "@/lib/csv/plan-tree";
import { streamSse, postJson } from "@/lib/llm/client-stream";
import { TokenUsageBar } from "@/components/token-usage-bar";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
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
import { PlanTree } from "@/components/plan-tree";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { IconAction } from "@/components/wizard/icon-action";
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
  Loader2,
  CircleStop,
  ArrowRight,
  Info,
  FileText,
} from "lucide-react";

export function StepAudit() {
  const {
    csvOriginal,
    archivisteObservation,
    setArchivisteObservation,
    briefMode,
    setBriefMode,
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
    planNotes,
    setStep,
    lastError,
    setLastError,
    resetAudit,
    usageAudit,
    setUsageAudit,
    durationAudit,
    setDurationAudit,
  } = useWizard();

  const [streamingResponse, setStreamingResponse] = useState("");
  const [streamingThinking, setStreamingThinking] = useState("");
  const [planTreeView, setPlanTreeView] = useState(true);
  const [confirmReset, setConfirmReset] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

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
        },
        {
          onText: (delta) => setStreamingResponse((prev) => prev + delta),
          onReasoning: (delta) => setStreamingThinking((prev) => prev + delta),
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
    } catch (err) {
      setLastError(err instanceof Error ? err.message : String(err));
    } finally {
      setAuditRunning(false);
    }
  };

  const stopAudit = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  const downloadReport = () => {
    const blob = new Blob([rapportAudit], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "rapport_audit.md";
    a.click();
    URL.revokeObjectURL(url);
  };

  const planOk = !!planValide && Object.keys(parsePlanTree(planValide)).length > 0;
  const hasResults = !!rapportAudit;
// ── Vue de lancement ─────────────────────────────────────────────────────────
  if (!hasResults) {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="obs" className="flex items-center gap-1.5">
            <StickyNote className="h-4 w-4" />
            Note contextuelle de l&apos;archiviste (optionnel)
          </Label>
          <Textarea
            id="obs"
            placeholder="Ex : Ces archives concernent le département RH, période 2015–2022. Attention aux dossiers personnels."
            value={archivisteObservation}
            onChange={(e) => setArchivisteObservation(e.target.value)}
            rows={4}
            disabled={auditRunning}
          />
          <p className="text-xs text-(--ink-500)">
            Cette note sera transmise au LLM comme contexte supplémentaire pour
            l&apos;audit.
          </p>
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
          </div>
          <p className="text-xs text-(--ink-500)">
            Ne demande au modèle que le plan de classement, sans état des lieux
            ni notes. Utile quand l&apos;audit a déjà été fait ou que le vrac est
            bien connu.
          </p>
        </div>

        {lastError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Erreur</AlertTitle>
            <AlertDescription className="text-xs">{lastError}</AlertDescription>
          </Alert>
        )}

        <div className="flex items-center justify-center gap-2">
          <Button onClick={runAudit} disabled={auditRunning} size="lg">
            {auditRunning ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Audit en cours…
              </>
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
        </div>

        {auditRunning && (
          <>
            {!streamingThinking && !streamingResponse && (
              <p className="text-sm text-(--ink-500)">
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
          {briefMode ? (
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
              <Button variant="outline" size="sm" onClick={downloadReport}>
                <Download className="mr-1 h-3.5 w-3.5" />
                Exporter en Markdown
              </Button>
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
              {planOk && (
                <div className="flex items-center gap-2">
                  <Switch
                    id="plan-tree-toggle"
                    checked={planTreeView}
                    onCheckedChange={setPlanTreeView}
                  />
                  <Label
                    htmlFor="plan-tree-toggle"
                    className="flex cursor-pointer items-center gap-1.5 text-sm"
                  >
                    <ListTree className="h-3.5 w-3.5" />
                    Vue arborescence
                  </Label>
                </div>
              )}
              {planOk && planTreeView ? (
                <div className="rounded-md border border-(--ink-100) bg-(--paper-50) p-3">
                  <PlanTree planValide={planValide} />
                </div>
              ) : (
                <StreamingMarkdown text={planValide} />
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
      <TokenUsageBar usage={usageAudit} durationMs={durationAudit} label="AUD-001" />

      {/* CTA de l'étape + relance. La navigation entre étapes passe par le
          fil d'Ariane. */}
      <div className="flex items-center justify-center gap-2">
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
      </div>

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
