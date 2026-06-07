"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useWizard, type ProjectSnapshot } from "@/lib/store";
import {
  listProjects,
  loadProject,
  saveProject,
  deleteProject,
  duplicateProject,
  renameProject,
  uniqueProjectName,
  type StoredProjectIndexEntry,
} from "@/lib/persistence";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ConfirmDialog } from "@/components/confirm-dialog";
import {
  Trash2,
  Plus,
  Settings,
  Pencil,
  Copy,
  PanelLeftClose,
  Check,
  X,
} from "lucide-react";

export function Sidebar({ onCollapse }: { onCollapse?: () => void } = {}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const state = useWizard();
  const {
    csvOriginal,
    rapportAudit,
    currentStem,
    currentName,
    applyProjectSnapshot,
    setCurrentProject,
    hydrateLlmConfig,
    hydrateUiPrefs,
    setSettingsModalOpen,
    reset,
  } = state;

  const [projects, setProjects] = useState<StoredProjectIndexEntry[]>([]);
  const [confirmNew, setConfirmNew] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Stem ciblé par une action de ligne (suppression / renommage).
  const [pendingStem, setPendingStem] = useState<string>("");
  const [renamingStem, setRenamingStem] = useState<string>("");
  const [renameValue, setRenameValue] = useState("");
  const [feedback, setFeedback] = useState<
    { kind: "ok" | "err"; msg: string } | null
  >(null);

  // Hydration : remplir l'index des projets après le mount pour éviter le
  // mismatch SSR/client (localStorage n'existe pas côté serveur).
  const hydratedRef = useRef(false);
  useEffect(() => {
    if (hydratedRef.current) return;
    hydratedRef.current = true;
    hydrateLlmConfig();
    hydrateUiPrefs();
    setProjects(listProjects());
  }, [hydrateLlmConfig, hydrateUiPrefs]);

  useEffect(() => {
    if (!feedback) return;
    const timeout = window.setTimeout(() => setFeedback(null), 4000);
    return () => window.clearTimeout(timeout);
  }, [feedback]);

  const restoredRef = useRef(false);
  useEffect(() => {
    if (restoredRef.current) return;
    const p = searchParams.get("p");
    if (!p) return;
    restoredRef.current = true;
    try {
      const proj = loadProject(p);
      // Snapshot + identité posés atomiquement (store) → l'effet de création
      // ne peut pas voir un rapport sans stem et fabriquer un doublon.
      applyProjectSnapshot(snapshotFromStored(proj), p, proj.name);
    } catch {
      const params = new URLSearchParams(searchParams.toString());
      params.delete("p");
      router.replace(params.toString() ? `/?${params.toString()}` : "/");
    }
  }, [searchParams, applyProjectSnapshot, router]);

  const hasData = csvOriginal !== null || Boolean(rapportAudit);

  const buildSnapshot = (): ProjectSnapshot => ({
    csvFilename: state.csvFilename,
    csvOriginal: state.csvOriginal,
    archivisteObservation: state.archivisteObservation,
    step: state.step,
    rapportAudit: state.rapportAudit,
    thinkingAudit: state.thinkingAudit,
    planValide: state.planValide,
    planValideOriginal: state.planValideOriginal,
    planNotes: state.planNotes,
    planModifie: state.planModifie,
    briefMode: state.briefMode,
    thinkingClassement: state.thinkingClassement,
    llmRawResponse: state.llmRawResponse,
    llmRawRows: state.llmRawRows,
    classementBatches: state.classementBatches,
    csvFinal: state.csvFinal,
    lastError: state.lastError,
  });

  const refreshProjects = () => setProjects(listProjects());

  const doNewProject = () => {
    reset(); // efface aussi l'identité (currentStem/currentName) dans le store
    setFeedback(null);
    setConfirmNew(false);
    const params = new URLSearchParams(searchParams.toString());
    params.delete("p");
    router.replace(params.toString() ? `/?${params.toString()}` : "/");
  };

  const handleNewProject = () => {
    // Un projet déjà matérialisé (currentStem) est auto-sauvegardé : on bascule
    // sans avertir. On ne prévient que pour un upload non encore persisté
    // (CSV chargé mais audit pas encore lancé → aucun projet créé).
    if (hasData && !currentStem) setConfirmNew(true);
    else doNewProject();
  };

  // ── Auto-save ──────────────────────────────────────────────────────────
  // Plus de sauvegarde manuelle : le projet est matérialisé au premier résultat
  // IA, puis chaque modification est persistée automatiquement (debounce).

  // Création différée : on attend le premier résultat IA (rapport d'audit) pour
  // créer le projet — évite de stocker les uploads abandonnés. Le nom par défaut
  // est dérivé du fichier CSV (renommable ensuite via le crayon).
  useEffect(() => {
    if (currentStem || !rapportAudit) return;
    try {
      const base = state.csvFilename
        .replace(/\.csv$/i, "")
        .replace(/[._-]+/g, " ")
        .trim();
      // Suffixe « (2) », « (3) »… si un projet du même nom existe déjà, pour ne
      // pas écraser un projet antérieur basé sur le même CSV (stem = clé).
      const name = uniqueProjectName(
        base || `Projet ${new Date().toLocaleString("fr-FR")}`,
      );
      const stem = saveProject(name, buildSnapshot());
      setCurrentProject(stem, name); // action store, pose l'identité
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setProjects(listProjects());
      const params = new URLSearchParams(searchParams.toString());
      params.set("p", stem);
      router.replace(`/?${params.toString()}`);
    } catch (e) {
      setFeedback({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rapportAudit, currentStem]);

  // Mises à jour : dès qu'une donnée persistée change, on ré-enregistre. Debounce
  // 800 ms pour ne pas écrire à chaque frappe (textarea d'observation). Les
  // drapeaux transitoires (auditRunning…) sont volontairement hors dépendances.
  useEffect(() => {
    if (!currentStem) return;
    const t = window.setTimeout(() => {
      try {
        saveProject(currentName, buildSnapshot(), currentStem);
      } catch (e) {
        setFeedback({
          kind: "err",
          msg: e instanceof Error ? e.message : String(e),
        });
      }
    }, 800);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    currentStem,
    currentName,
    state.csvFilename,
    state.csvOriginal,
    state.archivisteObservation,
    state.step,
    state.rapportAudit,
    state.thinkingAudit,
    state.planValide,
    state.planValideOriginal,
    state.planNotes,
    state.planModifie,
    state.thinkingClassement,
    state.llmRawResponse,
    state.llmRawRows,
    state.classementBatches,
    state.csvFinal,
    state.lastError,
  ]);

  const handleLoad = (stem: string) => {
    if (!stem) return;
    try {
      const proj = loadProject(stem);
      applyProjectSnapshot(snapshotFromStored(proj), proj.stem, proj.name);
      const params = new URLSearchParams(searchParams.toString());
      params.set("p", proj.stem);
      router.replace(`/?${params.toString()}`);
      // Pas de toast « chargé » : la ligne active surlignée suffit comme retour.
    } catch (e) {
      setFeedback({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    }
  };

  const handleDelete = () => {
    if (!pendingStem) return;
    try {
      if (pendingStem === currentStem) {
        setCurrentProject("", "");
        const params = new URLSearchParams(searchParams.toString());
        params.delete("p");
        router.replace(params.toString() ? `/?${params.toString()}` : "/");
      }
      deleteProject(pendingStem);
      setProjects(listProjects());
      setPendingStem("");
      // Pas de toast « supprimé » : la disparition de la ligne suffit.
    } catch (e) {
      setFeedback({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    }
  };

  const handleDuplicate = (stem: string) => {
    try {
      duplicateProject(stem);
      refreshProjects();
    } catch (e) {
      setFeedback({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    }
  };

  const startRename = (stem: string, name: string) => {
    setRenamingStem(stem);
    setRenameValue(name);
  };

  const cancelRename = () => {
    setRenamingStem("");
    setRenameValue("");
  };

  const commitRename = () => {
    const stem = renamingStem;
    const name = renameValue.trim();
    if (!stem || !name) {
      cancelRename();
      return;
    }
    try {
      const newStem = renameProject(stem, name);
      refreshProjects();
      if (stem === currentStem) {
        setCurrentProject(newStem, name);
        const params = new URLSearchParams(searchParams.toString());
        params.set("p", newStem);
        router.replace(`/?${params.toString()}`);
      }
    } catch (e) {
      setFeedback({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    }
    cancelRename();
  };

  return (
    <aside className="flex w-80 shrink-0 flex-col border-r border-(--ink-100) bg-(--paper-100) p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <ConfirmDialog
        open={confirmNew}
        onOpenChange={setConfirmNew}
        title="Démarrer un nouveau projet ?"
        description="Le projet en cours n'a pas été sauvegardé et sera perdu. Cette action est irréversible."
        confirmLabel="Continuer"
        onConfirm={doNewProject}
      />

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Supprimer ce projet ?"
        description={
          <>
            Le projet «&nbsp;
            <strong>
              {projects.find((p) => p.stem === pendingStem)?.name ?? pendingStem}
            </strong>
            &nbsp;» sera définitivement supprimé du stockage local. Cette action
            est irréversible.
          </>
        }
        confirmLabel="Supprimer"
        destructive
        onConfirm={handleDelete}
      />

      {/* ── En-tête Projets (au même niveau que le bouton de fermeture) ─ */}
      <div className="flex items-center justify-between gap-2">
        <h2 className="m-0 flex items-center gap-2 text-sm font-medium">
          Projets
        </h2>
        {onCollapse && (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={onCollapse}
            aria-label="Réduire le panneau"
            title="Réduire le panneau"
            className="hover:bg-(--ink-100) hover:text-(--ink-800) dark:hover:bg-zinc-800"
          >
            <PanelLeftClose className="h-4.5 w-4.5" />
          </Button>
        )}
      </div>

      <Button
        className="mt-3 w-full"
        type="button"
        variant="outline"
        size="sm"
        onClick={handleNewProject}
      >
        <Plus className="mr-1 h-3.5 w-3.5" />
        Nouveau projet
      </Button>

      {/* ── Liste des projets (façon conversations) ──────────────────── */}
      <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
        {projects.length === 0 ? (
          <p className="text-xs text-(--ink-500)">Aucun projet sauvegardé.</p>
        ) : (
          <ul className="space-y-0.5">
            {projects.map((p) => {
              const active = p.stem === currentStem;
              const isRenaming = p.stem === renamingStem;
              return (
                <li key={p.stem}>
                  {isRenaming ? (
                    <div className="flex items-center gap-1 px-1 py-1">
                      <Input
                        autoFocus
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitRename();
                          if (e.key === "Escape") cancelRename();
                        }}
                        className="h-7 text-xs"
                      />
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={commitRename}
                        aria-label="Valider le renommage"
                        title="Valider"
                      >
                        <Check className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        onClick={cancelRename}
                        aria-label="Annuler le renommage"
                        title="Annuler"
                      >
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ) : (
                    <div
                      className={`group flex items-center gap-1 rounded-md px-2 py-1.5 ${
                        active
                          ? "bg-(--ink-100) dark:bg-zinc-800"
                          : "hover:bg-(--ink-100)/60 dark:hover:bg-zinc-800/60"
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => handleLoad(p.stem)}
                        title={p.csvFilename ? `${p.name} — ${p.csvFilename}` : p.name}
                        className="min-w-0 flex-1 truncate text-left text-sm focus-visible:outline-none"
                      >
                        {p.name}
                      </button>
                      <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => startRename(p.stem, p.name)}
                          aria-label="Renommer ce projet"
                          title="Renommer"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => handleDuplicate(p.stem)}
                          aria-label="Dupliquer ce projet"
                          title="Dupliquer"
                        >
                          <Copy className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          onClick={() => {
                            setPendingStem(p.stem);
                            setConfirmDelete(true);
                          }}
                          aria-label="Supprimer ce projet"
                          title="Supprimer"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* ── Pied : Paramètres ──────────────────────────────────────────── */}
      <div className="mt-4 border-t border-(--ink-100) pt-3 dark:border-zinc-800">
        <Button
          type="button"
          variant="ghost"
          size="default"
          className="w-full justify-start text-sm hover:bg-(--ink-100) hover:text-(--ink-800) dark:hover:bg-zinc-800"
          onClick={() => setSettingsModalOpen(true)}
        >
          <Settings className="mr-2 h-4.5 w-4.5" />
          Paramètres
        </Button>
      </div>

      {/* Toast flottant : erreurs d'enregistrement uniquement (ex. quota
          localStorage dépassé). L'auto-save réussi reste silencieux.
          Fixé en bas, il ne décale pas la liste et s'efface seul (4 s). */}
      {feedback && (
        <div
          className="fixed bottom-4 left-1/2 z-50 w-[min(90vw,22rem)] -translate-x-1/2"
          role="status"
          aria-live="polite"
        >
          <Alert
            variant={feedback.kind === "ok" ? "success" : "destructive"}
            className="shadow-lg"
          >
            <AlertDescription className="text-xs">
              {feedback.msg}
            </AlertDescription>
          </Alert>
        </div>
      )}
    </aside>
  );
}

function snapshotFromStored(stored: {
  csvFilename: string;
  csvOriginal: import("@/lib/csv/types").SedaRow[] | null;
  archivisteObservation: string;
  step: import("@/lib/store").WizardStep;
  rapportAudit: string;
  thinkingAudit: string;
  planValide: string;
  planValideOriginal: string;
  planNotes: string;
  planModifie: boolean;
  briefMode?: boolean;
  thinkingClassement: string;
  llmRawResponse: string;
  llmRawRows: import("@/lib/csv/types").LlmClassementRow[] | null;
  classementBatches?: import("@/lib/csv/types").ClassementBatch[] | null;
  csvFinal: import("@/lib/csv/types").ResipResult | null;
  lastError: string;
}): ProjectSnapshot {
  return {
    csvFilename: stored.csvFilename,
    csvOriginal: stored.csvOriginal,
    archivisteObservation: stored.archivisteObservation,
    step: stored.step,
    rapportAudit: stored.rapportAudit,
    thinkingAudit: stored.thinkingAudit,
    planValide: stored.planValide,
    planValideOriginal: stored.planValideOriginal,
    planNotes: stored.planNotes,
    planModifie: stored.planModifie,
    briefMode: stored.briefMode ?? false,
    thinkingClassement: stored.thinkingClassement,
    llmRawResponse: stored.llmRawResponse,
    llmRawRows: stored.llmRawRows,
    classementBatches: stored.classementBatches ?? null,
    csvFinal: stored.csvFinal,
    lastError: stored.lastError,
  };
}
