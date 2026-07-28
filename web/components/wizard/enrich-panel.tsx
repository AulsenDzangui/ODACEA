"use client";

import { useState } from "react";
import { useWizard } from "@/lib/store";
import { useT } from "@/lib/i18n";
import {
  enrichCsv,
  formatApiError,
  type EnrichResult,
} from "@/lib/llm/client-stream";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  ScanText,
  ShieldAlert,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Download,
} from "lucide-react";

/**
 * Panneau d'enrichissement local (étape 0 facultative, backend local).
 *
 * Transport pur : collecte la racine locale du vrac + les options, appelle
 * `POST /enrich` (le moteur lit les binaires et renvoie le CSV enrichi en texte),
 * puis remonte ce CSV à l'appelant via `onEnriched` — qui le réinjecte dans
 * `/parse` (seule source d'analyse CSV). Aucune logique métier en TypeScript.
 *
 * Masqué en mode démonstration (l'endpoint est refusé côté serveur) : le parent
 * ne rend ce composant qu'en backend local.
 */
export function EnrichPanel({
  csvText,
  onEnriched,
}: {
  csvText: string;
  onEnriched: (enrichedCsv: string) => void | Promise<void>;
}) {
  const t = useT();
  // Racine mémorisée au store : partagée avec l'import direct d'un dossier
  // et l'application physique — pré-remplie ici, mise à jour à la frappe.
  const { sourceRoot, setSourceRoot } = useWizard();
  const [fingerprint, setFingerprint] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EnrichResult | null>(null);

  const run = async () => {
    if (!sourceRoot.trim() || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await enrichCsv({
        csv: csvText,
        sourceRoot: sourceRoot.trim(),
        overwrite,
        fingerprint,
      });
      setResult(res);
      // Réinjecte le CSV enrichi dans le parcours (re-parse côté moteur).
      await onEnriched(res.enrichedCsv);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(false);
    }
  };

  // Télécharge le CSV enrichi du dernier run pour vérifier le travail
  // d'enrichissement. Le moteur sérialise déjà en `;` + QUOTE_ALL ; aucun appel
  // réseau (le CSV est déjà en mémoire). Pas de BOM : comme le CSV final, Resip
  // rejette le header avec BOM (le ﻿ se colle à "ID").
  const downloadEnriched = () => {
    if (!result) return;
    const blob = new Blob([result.enrichedCsv], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "vrac_enrichi.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Accordion type="single" collapsible>
      <AccordionItem value="enrich">
        <AccordionTrigger>
          <span className="flex items-center gap-2">
            <ScanText className="h-4 w-4 text-(--ink-500)" />
            {t.enrich.title}
          </span>
        </AccordionTrigger>
        <AccordionContent>
          <div className="space-y-3 pt-1">
            <p className="text-sm text-(--ink-600)">{t.enrich.intro}</p>

            {/* <Alert>
              <ShieldAlert className="h-4 w-4" />
              <AlertTitle>{t.enrich.accessWarningTitle}</AlertTitle>
              <AlertDescription className="text-sm">
                {t.enrich.accessWarningBody}
              </AlertDescription>
            </Alert> */}

            <div className="space-y-1.5">
              <Label htmlFor="enrich-source-root" className="text-sm">
                {t.enrich.sourceRootLabel}
              </Label>
              <Input
                id="enrich-source-root"
                value={sourceRoot}
                onChange={(e) => setSourceRoot(e.target.value)}
                placeholder={t.enrich.sourceRootPlaceholder}
                disabled={busy}
              />
              {/* <p className="text-xs text-(--ink-400)">
                {t.enrich.sourceRootHelp}
              </p> */}
            </div>

            <div className="flex items-center justify-between gap-4">
              <Label htmlFor="enrich-fingerprint" className="text-sm font-normal">
                {t.enrich.fingerprintLabel}
              </Label>
              <Switch
                id="enrich-fingerprint"
                checked={fingerprint}
                onCheckedChange={setFingerprint}
                disabled={busy}
              />
            </div>
            <div className="flex items-center justify-between gap-4">
              <Label htmlFor="enrich-overwrite" className="text-sm font-normal">
                {t.enrich.overwriteLabel}
              </Label>
              <Switch
                id="enrich-overwrite"
                checked={overwrite}
                onCheckedChange={setOverwrite}
                disabled={busy}
              />
            </div>

            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <Button
                onClick={run}
                disabled={busy || !sourceRoot.trim()}
                className="w-full sm:w-auto"
              >
                {busy ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {t.enrich.running}
                  </>
                ) : (
                  <>
                    <ScanText className="mr-2 h-4 w-4" />
                    {t.enrich.run}
                  </>
                )}
              </Button>

              {result && (
                <Button
                  variant="outline"
                  onClick={downloadEnriched}
                  disabled={busy}
                  className="w-full sm:w-auto"
                >
                  <Download className="mr-2 h-4 w-4" />
                  {t.enrich.download}
                </Button>
              )}
            </div>

            {error && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>{t.enrich.errorTitle}</AlertTitle>
                <AlertDescription className="text-sm whitespace-pre-line">
                  {error}
                </AlertDescription>
              </Alert>
            )}

            {result && (
              <Alert variant="success">
                <CheckCircle2 />
                <AlertTitle>{t.enrich.successTitle}</AlertTitle>
                <AlertDescription className="text-sm">
                  <div className="space-y-1">
                    {result.report && (
                      <>
                        <p>
                          {t.enrich.descriptionSummary(
                            result.report.enriched,
                            result.report.totalItems,
                          )}
                        </p>
                        <p className="text-xs text-(--ink-500)">
                          {t.enrich.descriptionDetail(
                            result.report.alreadyFilled,
                            result.report.noText,
                            result.report.unsupported,
                            result.report.missing,
                          )}
                        </p>
                      </>
                    )}
                    {result.fingerprint && (
                      <p>
                        {t.enrich.fingerprintSummary(
                          result.fingerprint.hashed,
                          result.fingerprint.totalItems,
                        )}
                      </p>
                    )}
                    {result.duplicates && (
                      <p>
                        {t.enrich.duplicatesSummary(
                          result.duplicates.groups,
                          result.duplicates.redundant,
                        )}
                      </p>
                    )}
                    <p className="text-xs text-(--ink-500)">
                      {t.enrich.descriptionUsedNotice}
                    </p>
                  </div>
                </AlertDescription>
              </Alert>
            )}
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
