"use client";

import { useState } from "react";
import {
  planMaterialize,
  planFromFolder,
  formatApiError,
  type PlanFromFolder,
} from "@/lib/llm/client-stream";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { InfoTip } from "@/components/ui/info-tip";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ConfirmDialog } from "@/components/confirm-dialog";
import {
  FolderTree,
  FolderInput,
  Loader2,
  AlertTriangle,
  CheckCircle2,
  ArrowRight,
} from "lucide-react";

/**
 * Édition du plan par l'Explorateur Windows — aller-retour dossiers
 * réels. **Backend local uniquement** (masqué en démonstration par le parent) :
 *
 * 1. « Matérialiser » écrit l'arborescence du plan courant en **dossiers vides
 *    réels** dans un répertoire de travail choisi (`POST /plan/materialize`).
 * 2. L'archiviste réorganise ces dossiers dans l'Explorateur (déplacer, renommer,
 *    créer, supprimer) avec ses gestes habituels.
 * 3. « Recharger depuis le dossier » re-scanne le répertoire et reconstruit le plan
 *    canonique (`POST /plan/from-folder`) avec un **aperçu des changements** ; une
 *    fois vérifié, « Adopter » remplace le plan validé.
 *
 * Transport pur : matérialisation, scan, reconstruction et diff vivent dans le
 * moteur Python (`core/plan_folders.py`). Le front n'envoie qu'un chemin + le texte
 * du plan et présente le résultat.
 */
export function PlanExplorerPanel({
  planValide,
  onAdopt,
}: {
  planValide: string;
  onAdopt: (plan: string) => void;
}) {
  const [workDir, setWorkDir] = useState("");
  const [clear, setClear] = useState(false);
  const [busy, setBusy] = useState<null | "materialize" | "scan">(null);
  const [error, setError] = useState<string | null>(null);
  const [materialized, setMaterialized] = useState<{
    folderCount: number;
    cleared: boolean;
  } | null>(null);
  const [scan, setScan] = useState<PlanFromFolder | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  const dir = workDir.trim();

  const doMaterialize = async (confirm: boolean) => {
    if (!dir || busy) return;
    setBusy("materialize");
    setError(null);
    setScan(null);
    try {
      const res = await planMaterialize(planValide, dir, { clear, confirm });
      setMaterialized({ folderCount: res.folderCount, cleared: res.cleared });
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(null);
    }
  };

  const onMaterializeClick = () => {
    // Le vidage détruit le contenu du répertoire — confirmation explicite.
    if (clear) setConfirmClear(true);
    else void doMaterialize(false);
  };

  const doScan = async () => {
    if (!dir || busy) return;
    setBusy("scan");
    setError(null);
    try {
      setScan(await planFromFolder(dir, planValide));
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(null);
    }
  };

  const adopt = () => {
    if (!scan) return;
    onAdopt(scan.plan);
    setScan(null);
    setMaterialized(null);
  };

  const changes = scan?.changes;
  const hasChanges =
    changes &&
    (changes.added.length ||
      changes.removed.length ||
      changes.renamed.length ||
      changes.moved.length);

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2">
        <FolderTree className="mt-0.5 h-4 w-4 shrink-0 text-(--ink-500)" />
        <div className="space-y-1">
          <p className="text-sm font-medium">
            Éditer le plan dans l&apos;Explorateur Windows
          </p>
          <p className="text-xs text-(--ink-500)">
            Matérialisez le plan en dossiers vides réels, réorganisez-les avec vos
            gestes habituels (déplacer, renommer, créer, supprimer), puis rechargez
            le résultat. Aucun fichier n&apos;est lu ni écrit — dossiers vides
            uniquement.
          </p>
        </div>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="plan-workdir" className="flex items-center gap-1.5 text-sm">
          Répertoire de travail (sur votre machine)
          <InfoTip label="À propos du répertoire de travail">
            Un dossier local vide de préférence. Les préfixes numériques (1_, 1-1_…)
            font que le tri de l&apos;Explorateur restitue l&apos;ordre du plan.
          </InfoTip>
        </Label>
        <Input
          id="plan-workdir"
          value={workDir}
          onChange={(e) => setWorkDir(e.target.value)}
          placeholder="Ex : D:\\travail\\plan_odacea"
          disabled={busy !== null}
        />
      </div>

      <div className="flex items-center justify-between gap-4">
        <Label htmlFor="plan-clear" className="flex items-center gap-1.5 text-sm font-normal">
          Vider le répertoire avant de matérialiser
          <InfoTip label="À propos du vidage">
            Supprime le contenu du répertoire de travail (uniquement lui) avant
            d&apos;y écrire l&apos;arborescence — pratique pour repartir propre.
            Confirmation demandée.
          </InfoTip>
        </Label>
        <Switch
          id="plan-clear"
          checked={clear}
          onCheckedChange={setClear}
          disabled={busy !== null}
        />
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <Button
          onClick={onMaterializeClick}
          disabled={busy !== null || !dir}
          variant="outline"
          className="w-full sm:w-auto"
        >
          {busy === "materialize" ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <FolderTree className="mr-2 h-4 w-4" />
          )}
          Matérialiser en dossiers vides
        </Button>
        <Button
          onClick={doScan}
          disabled={busy !== null || !dir}
          variant="outline"
          className="w-full sm:w-auto"
        >
          {busy === "scan" ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <FolderInput className="mr-2 h-4 w-4" />
          )}
          Recharger depuis le dossier
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Erreur</AlertTitle>
          <AlertDescription className="text-xs whitespace-pre-line">
            {error}
          </AlertDescription>
        </Alert>
      )}

      {materialized && !scan && (
        <Alert variant="success">
          <CheckCircle2 />
          <AlertDescription className="text-xs">
            {materialized.folderCount} dossier(s) écrit(s)
            {materialized.cleared ? " (répertoire vidé au préalable)" : ""}.
            Réorganisez-les dans l&apos;Explorateur, puis « Recharger depuis le
            dossier ».
          </AlertDescription>
        </Alert>
      )}

      {scan && (
        <div className="space-y-2 rounded-md border border-(--ink-100) bg-(--paper-0) p-3">
          <p className="text-sm font-medium">
            Plan re-scanné : {scan.folderCount} dossier(s)
          </p>
          {scan.warnings.map((w, i) => (
            <p key={i} className="flex items-start gap-1.5 text-xs text-(--ink-500)">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {w}
            </p>
          ))}

          {changes?.identical ? (
            <p className="text-xs text-(--ink-500)">
              Aucun changement par rapport au plan actuel.
            </p>
          ) : hasChanges ? (
            <ul className="space-y-0.5 text-xs">
              {changes!.renamed.map((c, i) => (
                <li key={`r${i}`} className="text-(--accent-700)">
                  Renommé : {c.from} → {c.to}
                </li>
              ))}
              {changes!.moved.map((c, i) => (
                <li key={`m${i}`} className="text-(--accent-700)">
                  Déplacé : {c.from} → {c.to}
                </li>
              ))}
              {changes!.added.map((c, i) => (
                <li key={`a${i}`} className="text-(--ink-700)">
                  Ajouté : {c}
                </li>
              ))}
              {changes!.removed.map((c, i) => (
                <li key={`d${i}`} className="text-(--danger-600)">
                  Supprimé : {c}
                </li>
              ))}
            </ul>
          ) : null}

          <Button size="sm" onClick={adopt} className="mt-1">
            <ArrowRight className="mr-1 h-3.5 w-3.5" />
            Adopter ce plan
          </Button>
        </div>
      )}

      <ConfirmDialog
        open={confirmClear}
        onOpenChange={setConfirmClear}
        title="Vider le répertoire de travail ?"
        description={`Tout le contenu de « ${dir} » sera supprimé avant d'y écrire l'arborescence du plan. Cette action ne touche que ce répertoire.`}
        confirmLabel="Vider et matérialiser"
        destructive
        onConfirm={() => doMaterialize(true)}
      />
    </div>
  );
}
