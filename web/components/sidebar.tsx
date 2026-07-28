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
  exportProjectJson,
  importProjectJson,
  estimateStorageUsage,
  LOCALSTORAGE_WARN_RATIO,
  LOCALSTORAGE_BUDGET_BYTES,
  type StoredProjectIndexEntry,
} from "@/lib/persistence";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ConfirmDialog } from "@/components/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import {
  Trash2,
  Plus,
  Settings,
  Pencil,
  Copy,
  PanelLeftClose,
  Check,
  X,
  Download,
  Upload,
  AlertTriangle,
  MoreHorizontal,
} from "lucide-react";

export function Sidebar({ onCollapse }: { onCollapse?: () => void } = {}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const state = useWizard();
  const {
    csvOriginal,
    rapportAudit,
    planValide,
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
  // Occupation estimée du localStorage (D9) — recalculée après chaque mutation
  // de la liste des projets ; déclenche une alerte quota au-delà du seuil.
  const [storageRatio, setStorageRatio] = useState(0);
  const importInputRef = useRef<HTMLInputElement>(null);

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
    sourceRoot: state.sourceRoot,
    archivisteObservation: state.archivisteObservation,
    step: state.step,
    rapportAudit: state.rapportAudit,
    thinkingAudit: state.thinkingAudit,
    planValide: state.planValide,
    planValideOriginal: state.planValideOriginal,
    planNotes: state.planNotes,
    planModifie: state.planModifie,
    planOrigin: state.planOrigin,
    classementDirectives: state.classementDirectives,
    briefMode: state.briefMode,
    referencePlan: state.referencePlan,
    referencePlanName: state.referencePlanName,
    referenceMode: state.referenceMode,
    thinkingClassement: state.thinkingClassement,
    llmRawResponse: state.llmRawResponse,
    llmRawRows: state.llmRawRows,
    classementBatches: state.classementBatches,
    csvFinal: state.csvFinal,
    lastError: state.lastError,
    usageAudit: state.usageAudit,
    usageClassementTotal: state.usageClassementTotal,
    durationAudit: state.durationAudit,
    durationClassementTotal: state.durationClassementTotal,
    promptVersionAudit: state.promptVersionAudit,
    promptVersionClassement: state.promptVersionClassement,
    modelAudit: state.modelAudit,
    modelClassement: state.modelClassement,
  });

  const refreshProjects = () => {
    setProjects(listProjects());
    setStorageRatio(estimateStorageUsage().ratio);
  };

  // Occupation initiale (après hydratation de l'index).
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStorageRatio(estimateStorageUsage().ratio);
  }, [projects.length]);

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

  // Création différée : on attend un premier acquis pour créer le projet —
  // évite de stocker les uploads abandonnés. Le nom par défaut est dérivé du
  // fichier CSV (renommable ensuite via le crayon).
  //
  // Cet acquis est le rapport d'audit **ou** un plan validé : un plan adopté
  // sans audit LLM est un travail à part entière, et il ouvre droit au
  // classement. Ne déclencher que sur le rapport laissait ces projets sans
  // `currentStem`, donc jamais sauvegardés — le classement qui suivait, lots
  // compris, était perdu à la fermeture de l'onglet.
  useEffect(() => {
    if (currentStem || !(rapportAudit || planValide)) return;
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
  }, [rapportAudit, planValide, currentStem]);

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
    state.planOrigin,
    state.thinkingClassement,
    state.llmRawResponse,
    state.llmRawRows,
    state.classementBatches,
    state.csvFinal,
    state.lastError,
    state.usageAudit,
    state.usageClassementTotal,
    state.durationAudit,
    state.durationClassementTotal,
    state.promptVersionAudit,
    state.promptVersionClassement,
    state.modelAudit,
    state.modelClassement,
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
        // Projet ouvert : on efface données **et** identité (reset), pas seulement
        // l'identité. Sinon l'effet de création différée verrait un rapport sans
        // stem et re-matérialiserait aussitôt le projet sous un nouveau stem
        // (la suppression semblerait sans effet). Un projet vierge s'ouvre.
        reset();
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

  const handleExport = (stem: string) => {
    try {
      const { filename, json } = exportProjectJson(stem);
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setFeedback({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    }
  };

  const handleImportFile = async (file: File) => {
    try {
      const { stem, name } = importProjectJson(await file.text());
      refreshProjects();
      setFeedback({ kind: "ok", msg: `Projet « ${name} » importé.` });
      handleLoad(stem);
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

      <div className="mt-3 flex gap-2">
        <Button
          className="flex-1"
          type="button"
          variant="outline"
          size="sm"
          onClick={handleNewProject}
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          Nouveau projet
        </Button>
        {/* Import d'un projet .json exporté (D9) — portabilité entre postes. */}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => importInputRef.current?.click()}
          aria-label="Importer un projet"
          title="Importer un projet (.json)"
        >
          <Upload className="h-3.5 w-3.5" />
        </Button>
        <input
          ref={importInputRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleImportFile(file);
            e.target.value = ""; // permet de réimporter le même fichier
          }}
        />
      </div>

      {/* Alerte quota localStorage (D9) : la persistance est entièrement
          côté client ; on prévient avant la saturation pour éviter les pertes
          d'auto-save. Exporter puis supprimer d'anciens projets libère la place. */}
      {storageRatio >= LOCALSTORAGE_WARN_RATIO && (
        <Alert variant="warning" className="mt-3">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription className="text-xs">
            Stockage local presque plein (
            {Math.round(storageRatio * 100)} % de ~
            {Math.round(LOCALSTORAGE_BUDGET_BYTES / (1024 * 1024))} Mo).
            Exportez puis supprimez d&apos;anciens projets pour éviter une perte
            d&apos;enregistrement.
          </AlertDescription>
        </Alert>
      )}

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
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label="Actions du projet"
                            title="Actions"
                            className="shrink-0 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100"
                          >
                            <MoreHorizontal className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start">
                          <DropdownMenuItem onSelect={() => startRename(p.stem, p.name)}>
                            <Pencil className="h-4 w-4" />
                            Renommer
                          </DropdownMenuItem>
                          <DropdownMenuItem onSelect={() => handleDuplicate(p.stem)}>
                            <Copy className="h-4 w-4" />
                            Dupliquer
                          </DropdownMenuItem>
                          <DropdownMenuItem onSelect={() => handleExport(p.stem)}>
                            <Download className="h-4 w-4" />
                            Exporter (.json)
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            className="text-destructive focus:bg-destructive/10 focus:text-destructive"
                            onSelect={() => {
                              setPendingStem(p.stem);
                              setConfirmDelete(true);
                            }}
                          >
                            <Trash2 className="h-4 w-4" />
                            Supprimer
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
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
  planOrigin?: import("@/lib/store").PlanOrigin;
  classementDirectives?: import("@/lib/csv/types").ClassementDirective[];
  briefMode?: boolean;
  referencePlan?: string;
  referencePlanName?: string;
  referenceMode?: string;
  thinkingClassement: string;
  llmRawResponse: string;
  llmRawRows: import("@/lib/csv/types").LlmClassementRow[] | null;
  classementBatches?: import("@/lib/csv/types").ClassementBatch[] | null;
  csvFinal: import("@/lib/csv/types").ResipResult | null;
  lastError: string;
  usageAudit?: import("@/lib/llm/client-stream").LlmUsage | null;
  usageClassementTotal?: import("@/lib/llm/client-stream").LlmUsage | null;
  durationAudit?: number | null;
  durationClassementTotal?: number | null;
  promptVersionAudit?: string | null;
  promptVersionClassement?: string | null;
  modelAudit?: string | null;
  modelClassement?: string | null;
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
    planOrigin: stored.planOrigin,
    classementDirectives: stored.classementDirectives ?? [],
    briefMode: stored.briefMode ?? false,
    referencePlan: stored.referencePlan ?? "",
    referencePlanName: stored.referencePlanName ?? "",
    referenceMode: stored.referenceMode ?? "inspire",
    thinkingClassement: stored.thinkingClassement,
    llmRawResponse: stored.llmRawResponse,
    llmRawRows: stored.llmRawRows,
    classementBatches: stored.classementBatches ?? null,
    csvFinal: stored.csvFinal,
    lastError: stored.lastError,
    usageAudit: stored.usageAudit ?? null,
    usageClassementTotal: stored.usageClassementTotal ?? null,
    durationAudit: stored.durationAudit ?? null,
    durationClassementTotal: stored.durationClassementTotal ?? null,
    promptVersionAudit: stored.promptVersionAudit ?? null,
    promptVersionClassement: stored.promptVersionClassement ?? null,
    modelAudit: stored.modelAudit ?? null,
    modelClassement: stored.modelClassement ?? null,
  };
}
