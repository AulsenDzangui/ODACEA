"use client";

import { useState } from "react";
import { useWizard } from "@/lib/store";
import { parseFromFolder, type ScanStats } from "@/lib/llm/client-stream";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  FolderSearch,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Download,
} from "lucide-react";

/**
 * Import direct d'un dossier local (backend local uniquement).
 *
 * Alternative à l'upload d'un CSV Archifiltre : le moteur **scanne** le dossier
 * du vrac (métadonnées seules, aucun binaire ouvert) et en dérive le CSV
 * canonique. Transport pur : le panneau n'envoie qu'un **chemin** via
 * `parseFromFolder` (`POST /parse/from-folder`) puis remonte le CSV dérivé à
 * l'appelant (`onImported`), qui le traite comme un CSV importé. Aucune logique
 * métier en TypeScript.
 */
export function FolderImportPanel({
  prep,
  batchSize,
  onImported,
}: {
  prep: Record<string, unknown>;
  batchSize: number;
  onImported: (derivedCsv: string, filename: string) => void | Promise<void>;
}) {
  const { sourceRoot, setSourceRoot } = useWizard();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scan, setScan] = useState<ScanStats | null>(null);
  const [derivedCsv, setDerivedCsv] = useState<string>("");

  const run = async () => {
    const root = sourceRoot.trim();
    if (!root || busy) return;
    setBusy(true);
    setError(null);
    setScan(null);
    try {
      const res = await parseFromFolder({ sourceRoot: root, prep, batchSize });
      setScan(res.scan);
      setDerivedCsv(res.derivedCsv);
      const name = root.replace(/[/\\]+$/, "").split(/[/\\]/).pop() || "vrac";
      await onImported(res.derivedCsv, `${name} (dossier local scanné)`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  // Télécharge le CSV Archifiltre dérivé (produire un export Archifiltre sans
  // Archifiltre est un sous-produit utile). Pas de BOM : comme le CSV final,
  // Resip rejette un header à BOM.
  const downloadDerived = () => {
    if (!derivedCsv) return;
    const blob = new Blob([derivedCsv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "vrac.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Accordion type="single" collapsible>
      <AccordionItem value="folder-import">
        <AccordionTrigger>
          <span className="flex items-center gap-2">
            <FolderSearch className="h-4 w-4 text-(--ink-500)" />
            Ou : importer directement un dossier local (sans Archifiltre)
          </span>
        </AccordionTrigger>
        <AccordionContent>
          <div className="space-y-3 pt-1">
            <p className="text-sm text-(--ink-600)">
              Le moteur scanne l&apos;arborescence du vrac sur cette machine et en
              dérive le CSV de métadonnées — pas besoin d&apos;exporter depuis
              Archifiltre. Seuls les noms, chemins et dates de fichiers sont lus ;
              le contenu des documents n&apos;est jamais ouvert.
            </p>

            <div className="space-y-1.5">
              <Label htmlFor="folder-source-root" className="text-sm">
                Racine du vrac (dossier local)
              </Label>
              <Input
                id="folder-source-root"
                value={sourceRoot}
                onChange={(e) => setSourceRoot(e.target.value)}
                placeholder="D:\\archives\\service_scolaire"
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
                    Scan en cours…
                  </>
                ) : (
                  <>
                    <FolderSearch className="mr-2 h-4 w-4" />
                    Scanner le dossier
                  </>
                )}
              </Button>

              {derivedCsv && (
                <Button
                  variant="outline"
                  onClick={downloadDerived}
                  disabled={busy}
                  className="w-full sm:w-auto"
                >
                  <Download className="mr-2 h-4 w-4" />
                  Télécharger le CSV dérivé
                </Button>
              )}
            </div>

            {error && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Le scan a échoué</AlertTitle>
                <AlertDescription className="text-sm whitespace-pre-line">
                  {error}
                </AlertDescription>
              </Alert>
            )}

            {scan && (
              <Alert variant="success">
                <CheckCircle2 />
                <AlertTitle>Dossier scanné</AlertTitle>
                <AlertDescription className="text-sm">
                  <div className="space-y-1">
                    <p>
                      {scan.itemCount.toLocaleString("fr-FR")} fichier(s),{" "}
                      {scan.folderCount.toLocaleString("fr-FR")} dossier(s).
                    </p>
                    {(scan.excludedCount > 0 || scan.skippedSymlinks > 0) && (
                      <p className="text-xs text-(--ink-500)">
                        {scan.excludedCount} entrée(s) système ignorée(s)
                        {scan.skippedSymlinks > 0
                          ? `, ${scan.skippedSymlinks} lien(s) symbolique(s) non suivi(s)`
                          : ""}
                        .
                      </p>
                    )}
                    <p className="text-xs text-(--ink-500)">
                      Dates issues de la date de modification des fichiers (pas
                      des dates métier). Quand un export Archifiltre existe, il
                      reste préférable.
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
