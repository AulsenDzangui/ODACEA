"use client";

import { useState } from "react";
import { planFromFolder, type PlanFromFolder } from "@/lib/llm/client-stream";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { FolderInput, Loader2, AlertTriangle } from "lucide-react";

/**
 * Choix d'un plan directement depuis un **dossier existant** du poste :
 * l'archiviste indique un répertoire, on le scanne (`planFromFolder`) et on
 * remonte le plan reconstruit à l'appelant.
 *
 * Transport pur : le scan et la reconstruction vivent dans le moteur
 * (`core/plan_folders.py`). Fonctionne uniquement lorsque le backend est local.
 */
export function PlanFolderPicker({
  placeholder = "Ex : D:\\archives\\mon_plan",
  buttonLabel = "Charger depuis le dossier",
  disabled,
  onScanned,
}: {
  placeholder?: string;
  buttonLabel?: string;
  disabled?: boolean;
  onScanned: (res: PlanFromFolder, dir: string) => void;
}) {
  const [dir, setDir] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    const d = dir.trim();
    if (!d || busy) return;
    setBusy(true);
    setError(null);
    try {
      onScanned(await planFromFolder(d), d);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-col gap-2 sm:flex-row">
        <Input
          value={dir}
          onChange={(e) => setDir(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void load();
            }
          }}
          placeholder={placeholder}
          disabled={disabled || busy}
          className="sm:flex-1"
        />
        <Button
          type="button"
          variant="outline"
          onClick={load}
          disabled={disabled || busy || !dir.trim()}
          className="sm:w-auto"
        >
          {busy ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <FolderInput className="mr-2 h-4 w-4" />
          )}
          {buttonLabel}
        </Button>
      </div>
      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription className="text-xs whitespace-pre-line">
            {error}
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
