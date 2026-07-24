"use client";

import { useState } from "react";
import { useWizard } from "@/lib/store";
import {
  applyPreview,
  applyClassement,
  type ApplyPreview,
  type ApplyStats,
} from "@/lib/llm/client-stream";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  FolderInput,
  Copy,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  ShieldCheck,
} from "lucide-react";

type LiveProgress = { copied: number; total: number; current: string };

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

/**
 * Application physique du classement (backend local uniquement).
 *
 * Copie chaque fichier du SIP produit vers une **arborescence cible distincte**,
 * l'original conservé intact. Transport pur : le panneau envoie les lignes RESIP
 * (`csvFinal.rows`) + deux chemins ; l'aperçu, les garde-fous et la copie vivent
 * dans le moteur (`core/apply_classement.py`). Deux temps : **aperçu obligatoire**
 * puis **application confirmée** avec progression.
 */
export function ApplyPanel({ rows }: { rows: Record<string, unknown>[] }) {
  const { sourceRoot, setSourceRoot } = useWizard();
  const [targetRoot, setTargetRoot] = useState("");
  const [resume, setResume] = useState(false);
  const [preview, setPreview] = useState<ApplyPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [progress, setProgress] = useState<LiveProgress | null>(null);
  const [stats, setStats] = useState<ApplyStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canPreview = sourceRoot.trim() && targetRoot.trim() && !previewing && !applying;

  const runPreview = async () => {
    if (!canPreview) return;
    setPreviewing(true);
    setError(null);
    setStats(null);
    setPreview(null);
    try {
      const p = await applyPreview(rows, sourceRoot.trim(), targetRoot.trim(), resume);
      setPreview(p);
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPreviewing(false);
    }
  };

  const runApply = async () => {
    if (!preview || preview.targetGuard || applying) return;
    setApplying(true);
    setError(null);
    setStats(null);
    setProgress({ copied: 0, total: preview.total, current: "" });
    try {
      const res = await applyClassement(
        {
          rows,
          sourceRoot: sourceRoot.trim(),
          targetRoot: targetRoot.trim(),
          resume,
          confirm: true,
        },
        {
          onProgress: (p) => {
            if (typeof p.copied === "number" && typeof p.total === "number") {
              setProgress({
                copied: p.copied,
                total: p.total,
                current: p.current ?? "",
              });
            }
          },
          onError: (e) => setError(errMsg(e)),
        },
      );
      const done = res.done as { stats?: ApplyStats } | null;
      if (done?.stats) setStats(done.stats);
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setApplying(false);
      setProgress(null);
    }
  };

  const pct = progress && progress.total > 0
    ? Math.round((progress.copied / progress.total) * 100)
    : 0;

  return (
    <div className="space-y-3 rounded-md border border-(--ink-200) bg-(--paper-75) px-4 py-3">
      <div className="flex items-center gap-2">
        <FolderInput className="h-4 w-4 text-(--ink-500)" />
        <p className="font-medium text-(--ink-700)">
          Appliquer le classement au fonds (copie locale)
        </p>
      </div>
      <p className="text-sm text-(--ink-600)">
        Copie chaque fichier vers la nouvelle arborescence, dans un dossier cible
        distinct. <strong>Le fonds d&apos;origine n&apos;est jamais modifié</strong>{" "}
        (copie seule — aucun déplacement ni suppression).
      </p>

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="apply-source-root" className="text-sm">
            Racine du fonds source
          </Label>
          <Input
            id="apply-source-root"
            value={sourceRoot}
            onChange={(e) => setSourceRoot(e.target.value)}
            placeholder="D:\\archives\\service_scolaire"
            disabled={applying}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="apply-target-root" className="text-sm">
            Répertoire cible (créé)
          </Label>
          <Input
            id="apply-target-root"
            value={targetRoot}
            onChange={(e) => {
              setTargetRoot(e.target.value);
              setPreview(null);
            }}
            placeholder="D:\\archives\\service_scolaire_classe"
            disabled={applying}
          />
        </div>
      </div>

      <div className="flex items-center justify-between gap-4">
        <Label htmlFor="apply-resume" className="text-sm font-normal">
          Reprendre une application interrompue (cible déjà peuplée autorisée)
        </Label>
        <Switch
          id="apply-resume"
          checked={resume}
          onCheckedChange={(v) => {
            setResume(v);
            setPreview(null);
          }}
          disabled={applying}
        />
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <Button
          variant="outline"
          onClick={runPreview}
          disabled={!canPreview}
          className="w-full sm:w-auto"
        >
          {previewing ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Analyse…
            </>
          ) : (
            <>Aperçu avant copie</>
          )}
        </Button>

        {preview && !preview.targetGuard && (
          <Button
            onClick={runApply}
            disabled={applying}
            className="w-full sm:w-auto"
          >
            {applying ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Copie en cours…
              </>
            ) : (
              <>
                <Copy className="mr-2 h-4 w-4" />
                Copier {preview.total} fichier(s)
              </>
            )}
          </Button>
        )}
      </div>

      {progress && (
        <div className="space-y-1">
          <div className="h-2 w-full overflow-hidden rounded-full bg-(--ink-100)">
            <div
              className="h-full bg-(--graphite-700) transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-xs text-(--ink-500)">
            {progress.copied} / {progress.total} copié(s)
            {progress.current ? ` · ${progress.current}` : ""}
          </p>
        </div>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>L&apos;application a échoué</AlertTitle>
          <AlertDescription className="text-sm whitespace-pre-line">
            {error}
          </AlertDescription>
        </Alert>
      )}

      {preview && preview.targetGuard && (
        <Alert variant="destructive">
          <ShieldCheck className="h-4 w-4" />
          <AlertTitle>Répertoire cible refusé</AlertTitle>
          <AlertDescription className="text-sm whitespace-pre-line">
            {preview.targetGuard.error}
            {"\n→ "}
            {preview.targetGuard.hint}
          </AlertDescription>
        </Alert>
      )}

      {preview && !preview.targetGuard && !stats && (
        <Alert>
          <FolderInput className="h-4 w-4" />
          <AlertTitle>Aperçu de la copie</AlertTitle>
          <AlertDescription className="text-sm">
            <div className="space-y-1">
              <p>{preview.total} fichier(s) à copier.</p>
              {preview.missingCount > 0 && (
                <p className="font-medium text-(--ink-700)">
                  {preview.missingCount} binaire(s) introuvable(s) sous la source
                  (ignorés).
                </p>
              )}
              {preview.collisionCount > 0 && (
                <p className="text-(--ink-500)">
                  {preview.collisionCount} collision(s) de nom cible dédoublonnée(s).
                </p>
              )}
              {preview.atRootCount > 0 && (
                <p className="text-(--ink-500)">
                  {preview.atRootCount} fichier(s) laissé(s) à la racine cible
                  (non classés / hors-plan).
                </p>
              )}
            </div>
          </AlertDescription>
        </Alert>
      )}

      {stats && (
        <Alert variant={stats.failed > 0 ? "destructive" : "success"}>
          <CheckCircle2 />
          <AlertTitle>
            {stats.failed > 0 ? "Copie terminée avec des erreurs" : "Copie terminée"}
          </AlertTitle>
          <AlertDescription className="text-sm">
            <div className="space-y-1">
              <p>
                {stats.copied} copié(s), {stats.skipped} sauté(s),{" "}
                {stats.failed} échec(s).
              </p>
              <p className="text-xs text-(--ink-500)">
                Cible : {stats.targetRoot}. Le fonds d&apos;origine est inchangé.
              </p>
              {stats.errors.length > 0 && (
                <ul className="list-inside list-disc text-xs text-(--ink-500)">
                  {stats.errors.slice(0, 5).map((e, i) => (
                    <li key={i}>
                      {e.sourceRel} : {e.error}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
