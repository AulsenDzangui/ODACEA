"use client";

import { useCallback, useEffect, useState } from "react";
import { useDropzone } from "react-dropzone";
import { useWizard } from "@/lib/store";
import { stringifyCsv } from "@/lib/csv/parse";
import { postJson } from "@/lib/llm/client-stream";
import { formatTokens, type TokenEstimate } from "@/lib/tokens/estimate";
import type { SedaRow } from "@/lib/csv/types";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { CsvPreview } from "@/components/csv-preview";
import { FolderImportPanel } from "@/components/wizard/folder-import-panel";
import { FileText, ArrowRight, AlertCircle, CheckCircle2, Sliders } from "lucide-react";

type ParsePayload = {
  rows: SedaRow[];
  columns: string[];
  validationErrors: string[];
  stats: { rowCount: number; itemCount: number; recordGrpCount: number };
  prepared?: {
    previewRows: SedaRow[];
    columns: string[];
    columnCount: number;
    itemCount: number;
  };
  tokenEstimate?: TokenEstimate;
};

export function StepUpload() {
  const {
    csvFilename,
    csvOriginal,
    csvErrors,
    tokenOptions,
    classementBatchSize,
    setCsv,
    setStep,
  } = useWizard();

  const [view, setView] = useState<ParsePayload | null>(null);
  const [loading, setLoading] = useState(false);

  const prep = {
    filterColumns: tokenOptions.filterColumns,
    cleanDates: tokenOptions.cleanDates,
    sampleItems: tokenOptions.sampleItems,
    sampleItemsN: tokenOptions.sampleItemsN,
    includeDescription: tokenOptions.includeDescription,
    // Sans effet sur /parse (le digest n'intervient qu'à l'audit) ; présent
    // pour garder l'objet prep uniforme avec le store.
    autoMeasures: tokenOptions.autoMeasures,
  };

  const onDrop = useCallback(
    async (files: File[]) => {
      const file = files[0];
      if (!file) return;
      const text = await file.text();
      setLoading(true);
      try {
        const payload = await postJson<ParsePayload>("/parse", {
          csv: text,
          prep,
          batchSize: classementBatchSize,
        });
        setCsv(file.name, payload.rows, payload.validationErrors);
        setView(payload);
      } catch (err) {
        setCsv(file.name, [], [err instanceof Error ? err.message : String(err)]);
        setView(null);
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setCsv, classementBatchSize, tokenOptions],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "text/csv": [".csv"], "application/vnd.ms-excel": [".csv"] },
    multiple: false,
  });

  // Import direct d'un dossier local : le CSV dérivé côté serveur est ingéré
  // exactement comme un CSV déposé (même passage par /parse, backend sans état).
  const onFolderImported = useCallback(
    async (derivedCsv: string, filename: string) => {
      setLoading(true);
      try {
        const payload = await postJson<ParsePayload>("/parse", {
          csv: derivedCsv,
          prep,
          batchSize: classementBatchSize,
        });
        setCsv(filename, payload.rows, payload.validationErrors);
        setView(payload);
      } catch (err) {
        setCsv(filename, [], [err instanceof Error ? err.message : String(err)]);
        setView(null);
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setCsv, classementBatchSize, tokenOptions],
  );

  // Rafraîchit l'aperçu préparé + l'estimation tokens quand les options changent
  // (le backend Python est la seule source ; on re-sérialise le CSV chargé).
  useEffect(() => {
    if (!csvOriginal || csvErrors.length > 0) return;
    const csv = stringifyCsv(csvOriginal);
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const payload = await postJson<ParsePayload>("/parse", {
          csv,
          prep,
          batchSize: classementBatchSize,
        });
        if (!cancelled) setView(payload);
      } catch {
        /* aperçu best-effort */
      }
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    csvOriginal,
    csvErrors.length,
    tokenOptions.filterColumns,
    tokenOptions.cleanDates,
    tokenOptions.sampleItems,
    tokenOptions.sampleItemsN,
    tokenOptions.includeDescription,
    classementBatchSize,
  ]);

  const previewRows = view?.prepared?.previewRows ?? null;
  const tokenEst = view?.tokenEstimate ?? null;
  const nOrigCols = view?.columns.length ?? 0;
  const nPreviewCols = view?.prepared?.columnCount ?? 0;
  const nOrigItems = view?.stats.itemCount ?? 0;
  const nSentItems = view?.prepared?.itemCount ?? 0;
  const isFiltered =
    !!previewRows &&
    (nPreviewCols < nOrigCols ||
      tokenOptions.cleanDates ||
      nSentItems < nOrigItems);
  const previewLabel = isFiltered
    ? "Aperçu du CSV envoyé au LLM (5 premières lignes)"
    : "Aperçu du CSV (5 premières lignes)";

  return (
    <div className="space-y-5">
      <div>
        <div
          {...getRootProps()}
          className={
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed p-10 text-center transition-colors " +
            (isDragActive
              ? "border-(--graphite-700) bg-(--paper-100)"
              : "border-(--ink-200) hover:bg-(--paper-100)")
          }
        >
          <input {...getInputProps()} />
          <FileText className="h-10 w-10 text-(--ink-400)" />
          {csvOriginal ? (
            <>
              <p className="font-medium text-(--ink-900)">{csvFilename}</p>
              <p className="text-sm text-(--ink-500)">
                {csvOriginal.length.toLocaleString("fr-FR")} ligne(s) chargée(s)
              </p>
              <p className="text-xs text-(--ink-500)">
                Cliquez ou déposez un autre fichier pour remplacer.
              </p>
            </>
          ) : (
            <>
              <p className="font-medium text-(--ink-900)">
                {loading
                  ? "Lecture du fichier…"
                  : "Déposez un CSV ici ou cliquez pour parcourir"}
              </p>
              <p className="text-sm text-(--ink-500)">
                CSV de métadonnées Archifiltre / Resip (SEDA) · séparateur&nbsp;; ou&nbsp;, · UTF-8
              </p>
            </>
          )}
        </div>
      </div>

      <FolderImportPanel
        prep={prep}
        batchSize={classementBatchSize}
        onImported={onFolderImported}
      />

      {csvErrors.length > 0 && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>CSV invalide — corrigez ces erreurs avant de continuer</AlertTitle>
          <AlertDescription>
            <ul className="list-inside list-disc text-sm">
              {csvErrors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {csvOriginal && csvErrors.length === 0 && (
        <>
          <Alert variant="success">
            <CheckCircle2 />
            <AlertDescription>
              {csvOriginal.length} lignes · {nOrigCols} colonnes
            </AlertDescription>
          </Alert>

          {tokenEst && (
            <div className="rounded-md border border-(--ink-200) bg-(--paper-75) px-4 py-3 text-sm">
              <p className="mb-2 font-medium text-(--ink-700)">Estimation d&apos;usage LLM</p>
              <div className="space-y-1 text-(--ink-600)">
                <div className="flex justify-between gap-4">
                  <span>AUD-001 — Audit</span>
                  <span className="font-mono text-(--ink-800) whitespace-nowrap">
                    ~{formatTokens(tokenEst.auditTokens)} tokens
                  </span>
                </div>
                <div className="flex justify-between gap-4">
                  <span>
                    CLA-001 — Classement
                    {tokenEst.classementBatches > 1 && (
                      <span className="text-(--ink-400)">
                        {" "}({tokenEst.classementBatches} lots)
                      </span>
                    )}
                    <span className="text-(--ink-400)">*</span>
                  </span>
                  <span className="font-mono text-(--ink-800) whitespace-nowrap">
                    ~{formatTokens(tokenEst.classementTotalTokens)} tokens
                  </span>
                </div>
                <div className="flex justify-between gap-4 border-t border-(--ink-200) pt-1.5 font-medium text-(--ink-800)">
                  <span>Total estimé</span>
                  <span className="font-mono whitespace-nowrap">
                    ~{formatTokens(tokenEst.totalTokens)} tokens
                  </span>
                </div>
              </div>
              <p className="mt-2 text-xs text-(--ink-400)">
                * Estimation basée sur le nombre de caractères (±20 %). CLA-001 exclut le plan d&apos;audit, non connu à cette étape.
              </p>
            </div>
          )}

          {previewRows && (
            <Accordion type="single" collapsible>
              <AccordionItem value="preview">
                <AccordionTrigger>{previewLabel}</AccordionTrigger>
                <AccordionContent>
                  <div className="space-y-2 pt-1">
                    {isFiltered && (
                      <p className="text-xs text-(--ink-500)">
                        {nPreviewCols} colonnes sur {nOrigCols}
                        {nSentItems < nOrigItems
                          ? ` · ${nSentItems}/${nOrigItems} fichiers`
                          : ""}{" "}
                        — voir <Sliders className="inline-block h-3 w-3 -translate-y-px" /> Optimisation des tokens pour modifier.
                      </p>
                    )}
                    <CsvPreview rows={previewRows} maxRows={5} />
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          )}

          <div className="flex justify-center">
            <Button size="lg" onClick={() => setStep("audit")}>
              Continuer vers l&apos;audit
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
