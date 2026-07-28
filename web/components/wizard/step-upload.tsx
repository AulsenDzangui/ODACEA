"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useDropzone } from "react-dropzone";
import { useWizard } from "@/lib/store";
import { useT } from "@/lib/i18n";
import { DEMO_MODE } from "@/lib/llm/config";
import { stringifyCsv } from "@/lib/csv/parse";
import { API_BASE, postJson, formatApiError } from "@/lib/llm/client-stream";
import { formatTokens, formatCostEur, formatSampleN, type TokenEstimate } from "@/lib/tokens/estimate";
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
import { StepActions } from "@/components/wizard/step-actions";
import { EnrichPanel } from "@/components/wizard/enrich-panel";
import { FolderImportPanel } from "@/components/wizard/folder-import-panel";
import { FileText, ArrowRight, AlertCircle, AlertTriangle, CheckCircle2, Sliders, PlayCircle, Loader2, ShieldCheck, BookOpen } from "lucide-react";

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
  const t = useT();
  const {
    csvFilename,
    csvOriginal,
    csvErrors,
    tokenOptions,
    classementBatchSize,
    modelId,
    baseUrl,
    setCsv,
    setStep,
    setTokenOptions,
  } = useWizard();

  const [view, setView] = useState<ParsePayload | null>(null);
  const [loading, setLoading] = useState(false);
  // Erreur de transport (backend injoignable, 502, réseau…) — distincte des
  // erreurs de validation du CSV (`csvErrors`), qui supposent un /parse réussi.
  const [serverError, setServerError] = useState<string | null>(null);

  const prep = {
    filterColumns: tokenOptions.filterColumns,
    cleanDates: tokenOptions.cleanDates,
    sampleItems: tokenOptions.sampleItems,
    sampleItemsN: tokenOptions.sampleItemsN,
    includeItems: !tokenOptions.foldersOnly,
    includeDescription: tokenOptions.includeDescription,
    // Sans effet sur /parse (le digest n'intervient qu'à l'audit) ; présent
    // pour garder l'objet prep uniforme avec le store.
    autoMeasures: tokenOptions.autoMeasures,
  };

  const processCsv = useCallback(
    async (filename: string, text: string) => {
      setLoading(true);
      setServerError(null);
      try {
        const payload = await postJson<ParsePayload>("/parse", {
          csv: text,
          prep,
          batchSize: classementBatchSize,
          // Modèle/endpoint courants : permet à /parse de joindre le coût €
          // pour un cloud connu (rien pour un modèle local/inconnu).
          model: modelId,
          baseUrl,
        });
        setCsv(filename, payload.rows, payload.validationErrors);
        setView(payload);
      } catch (err) {
        // Échec de transport (502, réseau…) : ce n'est pas une erreur de CSV.
        setCsv(filename, [], []);
        setView(null);
        setServerError(formatApiError(err));
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setCsv, classementBatchSize, tokenOptions, modelId, baseUrl],
  );

  const onDrop = useCallback(
    async (files: File[]) => {
      const file = files[0];
      if (!file) return;
      await processCsv(file.name, await file.text());
    },
    [processCsv],
  );

  // Étape 0 d'enrichissement local : le moteur a produit un CSV enrichi
  // (descriptions / empreintes) ; on le réinjecte via /parse (source unique) et
  // on active « Inclure la description » pour qu'audit/classement la transmettent.
  const handleEnriched = useCallback(
    async (enrichedCsv: string) => {
      await processCsv(csvFilename, enrichedCsv);
      setTokenOptions({ includeDescription: true });
    },
    [processCsv, csvFilename, setTokenOptions],
  );

  // Import direct d'un dossier local : le moteur a scanné l'arborescence
  // et dérivé le CSV canonique ; on le traite comme un CSV importé (source unique
  // /parse). La racine reste mémorisée au store (pré-remplissage enrich/application).
  const handleFolderImported = useCallback(
    async (derivedCsv: string, filename: string) => {
      await processCsv(filename, derivedCsv);
    },
    [processCsv],
  );

  // Démo : charge le jeu de données embarqué servi par le backend (aucun upload
  // utilisateur possible).
  const loadDemo = useCallback(async () => {
    setLoading(true);
    setServerError(null);
    try {
      const res = await fetch(`${API_BASE}/demo/csv`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      await processCsv("Démonstration — Mairie Saint-Genis (Affaires scolaires)", text);
    } catch (err) {
      setServerError(
        "Impossible de charger le jeu de démonstration : " +
          (err instanceof Error ? err.message : String(err)),
      );
      setLoading(false);
    }
  }, [processCsv]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "text/csv": [".csv"], "application/vnd.ms-excel": [".csv"] },
    multiple: false,
  });

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
          model: modelId,
          baseUrl,
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
    tokenOptions.foldersOnly,
    tokenOptions.includeDescription,
    classementBatchSize,
    modelId,
    baseUrl,
  ]);

  const previewRows = view?.prepared?.previewRows ?? null;
  const tokenEst = view?.tokenEstimate ?? null;
  // Recommandation de budget d'entrée AUD-001 — calculée côté moteur.
  const budget = tokenEst?.budgetRecommendation ?? null;
  // Delta de tokens d'audit au réglage recommandé (présentation seule).
  const budgetTokenDelta = budget
    ? budget.estimatedAuditTokensAtRecommended - tokenEst!.auditTokens
    : 0;
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
      {DEMO_MODE ? (
        <div className="space-y-3">
          <Alert>
            <ShieldCheck className="h-4 w-4" />
            <AlertTitle>Mode démonstration</AlertTitle>
            <AlertDescription className="text-sm">
              Pour préserver la confidentialité, l&apos;import de vos fichiers est
              désactivé. La démonstration s&apos;appuie sur un jeu de données fictif
              (service des affaires scolaires d&apos;une mairie) généré par IA. Limitée à
              deux essais par étape, par jour et par visiteur.
            </AlertDescription>
          </Alert>
          <div className="flex flex-col items-center justify-center gap-3 rounded-md border-2 border-dashed border-(--ink-200) p-10 text-center">
            <FileText className="h-10 w-10 text-(--ink-400)" />
            {csvOriginal ? (
              <>
                <p className="font-medium text-(--ink-900)">{csvFilename}</p>
                <p className="text-sm text-(--ink-500)">
                  {csvOriginal.length.toLocaleString("fr-FR")} ligne(s) chargée(s)
                </p>
              </>
            ) : (
              <>
                <p className="font-medium text-(--ink-900)">
                  Jeu de données de démonstration
                </p>
                <Button size="lg" onClick={loadDemo} disabled={loading}>
                  {loading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Chargement…
                    </>
                  ) : (
                    <>
                      <PlayCircle className="mr-2 h-4 w-4" />
                      Voir la démonstration
                    </>
                  )}
                </Button>
              </>
            )}
          </div>
        </div>
      ) : (
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

          {/* Onboarding (D7) : démarrer sans fichier en un clic + accès au
              guide. Affiché tant qu'aucun CSV n'est chargé. */}
          {!csvOriginal && (
            <div className="mt-3 flex flex-col items-center gap-2 text-center sm:flex-row sm:justify-center">
              <span className="text-sm text-(--ink-500)">
                {t.onboarding.noFileYet}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={loadDemo}
                disabled={loading}
              >
                {loading ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                ) : (
                  <PlayCircle className="mr-1.5 h-3.5 w-3.5" />
                )}
                {loading ? t.onboarding.loading : t.onboarding.loadDemo}
              </Button>
              <Button asChild variant="ghost" size="sm">
                <Link href="/docs">
                  <BookOpen className="mr-1.5 h-3.5 w-3.5" />
                  {t.onboarding.openGuide}
                </Link>
              </Button>
            </div>
          )}
        </div>
      )}

      {/* — import direct d'un dossier local (alternative à l'upload CSV).
          Backend local uniquement : l'endpoint /parse/from-folder est refusé en
          démonstration (il scanne des dossiers sur la machine de l'archiviste). */}
      {!DEMO_MODE && (
        <FolderImportPanel
          prep={prep}
          batchSize={classementBatchSize}
          model={modelId}
          baseUrl={baseUrl}
          onImported={handleFolderImported}
        />
      )}

      {serverError && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Le serveur n&apos;a pas pu traiter le fichier</AlertTitle>
          <AlertDescription className="text-sm whitespace-pre-line">
            {serverError}
          </AlertDescription>
        </Alert>
      )}

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

          {/* enrichissement local (étape 0, facultatif). Réservé au backend
              local : l'endpoint /enrich est refusé en démonstration (il lit des
              fichiers sur la machine de l'archiviste). */}
          {!DEMO_MODE && (
            <EnrichPanel
              csvText={stringifyCsv(csvOriginal)}
              onEnriched={handleEnriched}
            />
          )}

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
                {/* Coût € indicatif — affiché seulement pour un modèle cloud
                    connu (rien pour un modèle local/inconnu : costEstimate null). */}
                {tokenEst.costEstimate && (
                  <div className="flex justify-between gap-4 font-medium text-(--ink-800)">
                    <span>
                      Coût d&apos;entrée estimé
                      <span className="text-(--ink-400)">
                        {" "}({tokenEst.costEstimate.label})
                      </span>
                      <span className="text-(--ink-400)">†</span>
                    </span>
                    <span className="font-mono whitespace-nowrap">
                      ~{formatCostEur(tokenEst.costEstimate.totalEur)}
                    </span>
                  </div>
                )}
                {/* Budget d'entrée AUD-001 — échantillon courant vs recommandé
                    pour la taille du vrac (calcul moteur, aucune logique métier en TS). */}
                {/* {budget && (
                  <div className="flex justify-between gap-4 border-t border-(--ink-200) pt-1.5">
                    <span>
                      Profondeur d&apos;entrée AUD-001
                      <span className="text-(--ink-400)"> (vrac {budget.tier})</span>
                      <span className="text-(--ink-400)">‡</span>
                    </span>
                    <span className="whitespace-nowrap text-(--ink-800)">
                      {budget.matchesRecommendation ? (
                        <span className="font-mono">
                          {formatSampleN(budget.currentSampleN)} ✓
                        </span>
                      ) : (
                        <span className="font-mono">
                          {formatSampleN(budget.currentSampleN)} → {formatSampleN(budget.recommendedSampleN)}
                        </span>
                      )}
                    </span>
                  </div>
                )} */}
              </div>
              {/* <p className="mt-2 text-xs text-(--ink-400)">
                * Estimation basée sur le nombre de caractères (±20 %). CLA-001 exclut le plan d&apos;audit, non connu à cette étape.
              </p>
              {tokenEst.costEstimate && (
                <p className="mt-1 text-xs text-(--ink-400)">
                  † Coût d&apos;entrée seul, indicatif (tarifs au {tokenEst.costEstimate.priceDate}, hors tokens de sortie). Modèles locaux : aucun coût au token.
                </p>
              )}
              {budget && (
                <p className="mt-1 text-xs text-(--ink-400)">
                  ‡ Échantillonnage des fichiers envoyés à l&apos;audit, recommandé selon la taille du vrac ({budget.itemCount.toLocaleString("fr-FR")} fichiers).{" "}
                  {budget.matchesRecommendation ? (
                    <>Réglage adapté&nbsp;: {budget.rationale}.</>
                  ) : (
                    <>
                      Recommandé&nbsp;: {formatSampleN(budget.recommendedSampleN)} (~{formatTokens(budget.estimatedAuditTokensAtRecommended)} tokens d&apos;audit,{" "}
                      {budgetTokenDelta === 0
                        ? "volume inchangé"
                        : `${budgetTokenDelta > 0 ? "+" : "−"}${formatTokens(Math.abs(budgetTokenDelta))}`}
                      ) — ajustable dans Optimisation des tokens. {budget.rationale}.
                    </>
                  )}{" "}
                  Paliers au {budget.tableDate}.
                </p>
              )} */}
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

          <StepActions>
            <Button size="lg" onClick={() => setStep("audit")}>
              Continuer vers l&apos;audit
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </StepActions>
        </>
      )}
    </div>
  );
}
