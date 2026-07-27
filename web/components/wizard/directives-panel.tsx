"use client";

import { useState } from "react";
import type { ClassementDirective } from "@/lib/csv/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { MessageSquarePlus, Trash2, FolderTree, Info } from "lucide-react";

/** Option de dossier du plan pour l'ancrage d'une consigne. */
export type DirectiveFolderOption = { tech: string; label: string };

/** Valeur du <Select> pour « au niveau du fonds » (pas d'ancrage). Sentinel non
 *  vide : Radix Select interdit une value vide. */
const FONDS = "__fonds__";

/**
 * Panneau des **consignes de classement de l'archiviste**. L'archiviste pose des
 * préconisations ancrées à un dossier du plan ou au niveau du fonds ; une
 * consigne peut **autoriser la création de sous-dossiers** sous le dossier visé.
 * Les consignes ne modifient pas le plan et sont réutilisées à chaque relance du
 * classement.
 *
 * Présentation pure : la sérialisation en bloc de prompt et la dérivation des
 * dossiers à création autorisée vivent dans le moteur (`core.cla_directives`).
 * Ce composant ne fait que collecter la liste et la remonter via `onChange`.
 */
export function DirectivesPanel({
  directives,
  onChange,
  folders,
  createdFolders = [],
}: {
  directives: ClassementDirective[];
  onChange: (d: ClassementDirective[]) => void;
  folders: DirectiveFolderOption[];
  /** Sous-dossiers créés au dernier classement — rappel informatif. */
  createdFolders?: string[];
}) {
  const [folder, setFolder] = useState<string>(FONDS);
  const [text, setText] = useState("");
  const [allowCreation, setAllowCreation] = useState(false);

  const labelFor = (tech: string) =>
    folders.find((f) => f.tech === tech)?.label ?? tech;

  const add = () => {
    const t = text.trim();
    if (!t) return;
    const entry: ClassementDirective = {
      text: t,
      allowCreation,
      ...(folder !== FONDS ? { folder } : {}),
    };
    onChange([...directives, entry]);
    setText("");
    setAllowCreation(false);
    setFolder(FONDS);
  };

  const remove = (i: number) => onChange(directives.filter((_, k) => k !== i));

  return (
    <div className="space-y-4" id="directives-panel">
      <div className="flex items-start gap-2">
        <FolderTree className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          Ajoutez des consignes pour guider le classement — au niveau du fonds ou
          ancrées à un dossier du plan. Une consigne peut autoriser l&apos;IA à
          créer des sous-dossiers (ex.&nbsp;: «&nbsp;un sous-dossier par
          employeur&nbsp;»). Les consignes sont réutilisées à chaque relance.
        </p>
      </div>

      {directives.length > 0 && (
        <ul className="space-y-2">
          {directives.map((d, i) => (
            <li
              key={i}
              className="flex items-start justify-between gap-3 rounded-md border bg-card px-3 py-2 text-sm"
            >
              <div className="min-w-0 space-y-0.5">
                <div className="font-medium">
                  {d.folder ? (
                    <span className="text-primary">{labelFor(d.folder)}</span>
                  ) : (
                    <span className="text-muted-foreground">Ensemble du fonds</span>
                  )}
                  {d.allowCreation && (
                    <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-normal text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                      création de sous-dossiers
                    </span>
                  )}
                </div>
                <div className="break-words text-muted-foreground">{d.text}</div>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={() => remove(i)}
                aria-label="Retirer la consigne"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="space-y-3 rounded-md border border-dashed p-3">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,14rem)_1fr]">
          <div className="space-y-1">
            <Label className="text-xs">Portée</Label>
            <Select value={folder} onValueChange={setFolder}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={FONDS}>Ensemble du fonds</SelectItem>
                {folders.map((f) => (
                  <SelectItem key={f.tech} value={f.tech}>
                    {f.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs" htmlFor="directive-text">
              Consigne
            </Label>
            <Input
              id="directive-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") add();
              }}
              placeholder="ex. regrouper CV, lettre de motivation et références par employeur"
            />
          </div>
        </div>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Switch
              id="directive-creation"
              checked={allowCreation}
              onCheckedChange={setAllowCreation}
            />
            <Label htmlFor="directive-creation" className="text-sm font-normal">
              Autoriser la création de sous-dossiers
            </Label>
          </div>
          <Button size="sm" onClick={add} disabled={!text.trim()}>
            <MessageSquarePlus className="mr-1.5 h-4 w-4" />
            Ajouter
          </Button>
        </div>
      </div>

      {createdFolders.length > 0 && (
        <Alert>
          <Info className="h-4 w-4" />
          <AlertTitle>
            {createdFolders.length} sous-dossier
            {createdFolders.length > 1 ? "s" : ""} créé
            {createdFolders.length > 1 ? "s" : ""} au dernier classement
          </AlertTitle>
          <AlertDescription>
            <p className="mb-1">
              L&apos;IA a créé ces sous-dossiers sous vos consignes&nbsp;:
            </p>
            <ul className="list-inside list-disc">
              {createdFolders.map((f) => (
                <li key={f}>{displayCreated(f)}</li>
              ))}
            </ul>
            <p className="mt-1 text-xs">
              Pour figer la structure, ajoutez-les à votre plan (étape d&apos;audit)
              puis relancez&nbsp;: le classement les réutilisera au lieu d&apos;en
              recréer.
            </p>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}

/** Nom technique d'un sous-dossier créé → libellé lisible (préfixe pointé). */
function displayCreated(tech: string): string {
  const m = tech.match(/^(\d[\d-]*)_(.*)/);
  if (m) return `${m[1].replace(/-/g, ".")} ${m[2].replace(/_/g, " ")}`;
  return tech.replace(/_/g, " ");
}
