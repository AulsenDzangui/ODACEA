"use client";

import type {
  ClassementBatch,
  CorrectionExample,
  LlmClassementRow,
  ResipResult,
  SedaRow,
} from "@/lib/csv/types";
import type { FolderDelete, FolderRename } from "@/lib/csv/plan-edit";
import type { Anomaly } from "@/lib/csv/anomalies";
import type { LlmUsage } from "@/lib/llm/client-stream";
import { plS } from "@/lib/utils";
import { DEMO_MODE } from "@/lib/llm/config";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Separator } from "@/components/ui/separator";
import { StreamingMarkdown } from "@/components/streaming-markdown";
import { ThinkingPanel } from "@/components/thinking-panel";
import { CsvPreview } from "@/components/csv-preview";
import { TokenUsageBar, sumUsage } from "@/components/token-usage-bar";
import { formatDuration } from "@/lib/tokens/estimate";
import { ReclassPanel } from "@/components/wizard/reclass-panel";
import { AnomaliesTable } from "@/components/wizard/anomalies-table";
import { ApplyPanel } from "@/components/wizard/apply-panel";
import { AdvancedSection } from "@/components/wizard/advanced-section";
import {
  Pencil,
  AlertCircle,
  AlertTriangle,
  FileText,
  StickyNote,
  Search,
  Download,
} from "lucide-react";

/**
 * Onglet « Outils » du classement — tout ce qui corrige, diagnostique ou
 * agit sur le résultat, séparé du rapport de lecture (`ClassementCoverageReport`,
 * onglet « Résultat ») pour ne pas noyer l'archiviste dans le débogage. Pure
 * présentation : aucune logique métier, tout est reçu en props/callbacks
 * du parent `StepClassement`.
 */
export function ClassementToolsPanel({
  llmRawRows,
  hasReclassWork,
  reclassAccordion,
  onReclassAccordionChange,
  reclassPanelLabel,
  lastError,
  csvOriginal,
  planValide,
  planValideOriginal,
  reclassBusy,
  onApplyCorrections,
  onCreateFolder,
  onRenameFolder,
  onDeleteFolder,
  reclassSearch,
  onLocateItem,
  nNoDate,
  coherenceErrors,
  anomalies,
  csvFinal,
  rowsExport,
  preCsvText,
  classementBatches,
  thinkingClassement,
  onDownloadRawLlmCsv,
  onDownloadRowsCsv,
  usageClassementTotal,
  usageAudit,
  durationClassementTotal,
  durationAudit,
  modelClassement,
}: {
  llmRawRows: LlmClassementRow[] | null;
  hasReclassWork: boolean;
  reclassAccordion: string;
  onReclassAccordionChange: (v: string) => void;
  reclassPanelLabel: string;
  lastError: string;
  csvOriginal: SedaRow[];
  planValide: string;
  planValideOriginal: string;
  reclassBusy: boolean;
  onApplyCorrections: (
    rows: LlmClassementRow[],
    corrections: CorrectionExample[],
  ) => Promise<void>;
  onCreateFolder: (parentTech: string | null, title: string) => string | null;
  onRenameFolder: (tech: string, title: string) => FolderRename | null;
  onDeleteFolder: (tech: string) => FolderDelete | null;
  reclassSearch: string;
  onLocateItem: ((path: string) => void) | undefined;
  nNoDate: number;
  coherenceErrors: string[];
  anomalies: Anomaly[];
  csvFinal: ResipResult;
  rowsExport: SedaRow[] | null;
  preCsvText: string;
  classementBatches: ClassementBatch[] | null;
  thinkingClassement: string;
  onDownloadRawLlmCsv: () => void;
  onDownloadRowsCsv: (rows: LlmClassementRow[] | null, suffix: string) => void;
  usageClassementTotal: LlmUsage | null;
  usageAudit: LlmUsage | null;
  durationClassementTotal: number | null;
  durationAudit: number | null;
  modelClassement: string | null;
}) {
  return (
    <div className="space-y-4 pt-3">
      {/* ── Rattrapage des non-classés (recentré) ────────────────────
          Seule retouche que se réserve ODACEA : rattacher au plan les items
          que l'IA a omis (sinon orphelins à la racine de l'export). Affiché
          uniquement s'il en reste — la retouche des items déjà classés
          relève de Resip, vers lequel ODACEA n'est qu'un passage. Le panneau
          ouvre par défaut sur les seuls problèmes (toggle désactivable) :
          fichiers non classés à rattacher et fichiers classés en double dont
          il faut retirer les exemplaires superflus. */}
      {llmRawRows && llmRawRows.length > 0 && hasReclassWork && (
        <Accordion
          type="single"
          collapsible
          id="reclass-panel"
          value={reclassAccordion}
          onValueChange={onReclassAccordionChange}
        >
          <AccordionItem value="reclass">
            <AccordionTrigger>
              <span className="flex items-center gap-1.5">
                <Pencil className="h-3.5 w-3.5" />
                {reclassPanelLabel}
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <div className="space-y-2 pt-2">
                {lastError && (
                  <Alert variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertDescription className="text-xs whitespace-pre-line">
                      {lastError}
                    </AlertDescription>
                  </Alert>
                )}
                <ReclassPanel
                  csvOriginal={csvOriginal}
                  planValide={planValide}
                  llmRawRows={llmRawRows}
                  busy={reclassBusy}
                  onApply={onApplyCorrections}
                  planOriginal={planValideOriginal}
                  onCreateFolder={onCreateFolder}
                  onRenameFolder={onRenameFolder}
                  onDeleteFolder={onDeleteFolder}
                  initialSearch={reclassSearch}
                />
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      )}

      {nNoDate > 0 && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            {nNoDate} Item{plS(nNoDate)} sans date. Vérifiez les champs
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

      {/* ── Triage des anomalies : groupées, filtrables, reliées
             au panneau de correction. ─────────────────────────── */}
      {anomalies.length > 0 && (
        <Accordion type="single" collapsible>
          <AccordionItem value="warns">
            <AccordionTrigger>
              <span className="flex items-center gap-1.5">
                <AlertTriangle className="h-3.5 w-3.5 text-(--warning-500)" />
                {anomalies.length} anomalie{plS(anomalies.length)} de conversion
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <div className="pt-2">
                <AnomaliesTable anomalies={anomalies} onLocate={onLocateItem} />
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      )}

      <Separator />

      {/* ── Pour aller plus loin (avancé) — replié par défaut ─────────────
          Vérification et diagnostic regroupés pour l'expert, sans alourdir la
          vue par défaut destinée à l'archiviste. Rien n'est retiré : tout
          reste atteignable, simplement replié. ─────────────────────────── */}
      <AdvancedSection title="Pour aller plus loin" icon={Search}>
        <Accordion type="single" collapsible>
          <AccordionItem value="apercu-final">
            <AccordionTrigger>
              <span className="flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5" />
                Aperçu du CSV final ({csvFinal.rows.length} lignes ·{" "}
                {csvFinal.columns.length} colonnes)
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <div className="space-y-1 pt-2">
                <p className="text-xs text-(--ink-500)">
                  Aperçu des 20 premières lignes seulement.
                </p>
                <CsvPreview rows={rowsExport ?? csvFinal.rows} maxRows={20} />
              </div>
            </AccordionContent>
          </AccordionItem>
        </Accordion>

        {!classementBatches && preCsvText && (
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

        {thinkingClassement && <ThinkingPanel thinking={thinkingClassement} />}

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
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={onDownloadRawLlmCsv}
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
                          {b.itemCount} item{plS(b.itemCount)} envoyé{plS(b.itemCount)} · {b.rows.length}{" "}
                          ligne{plS(b.rows.length)} produite{plS(b.rows.length)}
                        </p>
                        {(b.preCsv ?? "").trim() && (
                          <Accordion
                            type="single"
                            collapsible
                            className="border-none bg-transparent px-0"
                          >
                            <AccordionItem value="demarche">
                              <AccordionTrigger className="py-1 text-xs font-medium text-(--ink-600)">
                                <span className="flex items-center gap-1.5">
                                  <StickyNote className="h-3 w-3" />
                                  Démarche de l&apos;IA
                                </span>
                              </AccordionTrigger>
                              <AccordionContent className="pb-1 text-xs">
                                <StreamingMarkdown
                                  text={(b.preCsv ?? "").trim()}
                                />
                              </AccordionContent>
                            </AccordionItem>
                          </Accordion>
                        )}
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
                                onDownloadRowsCsv(b.rows, `_lot${i + 1}`)
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
                      onClick={onDownloadRawLlmCsv}
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
            <TokenUsageBar usage={usageClassementTotal} durationMs={durationClassementTotal} label="CLA-001" model={modelClassement} />
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
      </AdvancedSection>

      {/* — application physique du classement : copie du SIP produit
          vers une arborescence cible (la source n'est jamais mutée). Backend
          local uniquement : l'endpoint /apply est refusé en démonstration. Une
          action physique sur disque mérite un opt-in explicite, pas un bloc
          toujours déployé. */}
      {!DEMO_MODE && csvFinal.rows.length > 0 && (
        <AdvancedSection title="Application physique du classement">
          <ApplyPanel rows={rowsExport ?? csvFinal.rows} />
        </AdvancedSection>
      )}
    </div>
  );
}
