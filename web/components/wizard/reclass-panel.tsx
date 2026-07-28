"use client";

import { useMemo, useState } from "react";
import type {
  CorrectionExample,
  LlmClassementRow,
  SedaRow,
} from "@/lib/csv/types";
import {
  parsePlanTree,
  parsePlanTitles,
  displayParts,
  sortKey,
} from "@/lib/csv/plan-tree";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/confirm-dialog";
import type { FolderRename, FolderDelete } from "@/lib/csv/plan-edit";
import {
  FolderPlus,
  Loader2,
  Pencil,
  RefreshCw,
  RotateCcw,
  Search,
  Trash2,
  X,
} from "lucide-react";

// ── Re-classement partiel ────────────────────────────────────────────────────
// Corriger la cible (et le titre) d'un item après le classement, puis
// re-finaliser : la finalisation est une passe Python pure — AUCUN appel LLM.
// Les non-classés (absents de la sortie LLM) peuvent être rattachés à un
// dossier du plan : une ligne est ajoutée à la sortie corrigée.

type Edit = { TargetFolder?: string; NewTitle?: string };

type Props = {
  csvOriginal: SedaRow[];
  planValide: string;
  llmRawRows: LlmClassementRow[];
  busy: boolean;
  /** Re-finalise avec les lignes corrigées ; rejette en cas d'erreur backend.
   * `corrections` = les corrections validées dans cette passe, exprimées en
   *  métadonnées seules (`Path;TargetFolder;NewTitle`) — l'appelant décide de les
   *  réinjecter ou non comme exemples few-shot (opt-in). */
  onApply: (
    rows: LlmClassementRow[],
    corrections: CorrectionExample[],
  ) => Promise<void>;
  /** Crée un dossier dans le plan validé sous `parentTech` (nom technique complet,
   *  ou `null` = premier niveau) et renvoie le nom technique du nouveau dossier —
   *  `null` si la création a échoué. L'appelant met à jour `planValide` (le moteur
   *  re-dérive l'arbre à la finalisation, seule source de vérité). */
  onCreateFolder: (parentTech: string | null, title: string) => string | null;
  /** Renomme un dossier créé à cette étape ; renvoie le remap (le préfixe peut
   *  changer) pour réaligner les affectations, ou `null` en cas d'échec. */
  onRenameFolder: (tech: string, title: string) => FolderRename | null;
  /** Supprime un dossier créé à cette étape (et son sous-arbre) ; renvoie le
   *  remap des frères décalés + les noms techniques disparus, ou `null`. */
  onDeleteFolder: (tech: string) => FolderDelete | null;
  /** Plan d'origine (avant retouches) : les dossiers absents de ce plan sont
   *  ceux créés par l'archiviste — seuls modifiables/supprimables ici, le reste
   *  du plan restant en lecture seule. */
  planOriginal: string;
  /** Filtre initial (lien depuis le tableau des anomalies). */
  initialSearch?: string;
};

// Valeurs sentinelles du `Select` de dossier cible : déclencher la création d'un
// dossier, et désigner le premier niveau (racine) comme parent dans le dialogue.
const CREATE_SENTINEL = "__create_folder__";
const ROOT_SENTINEL = "__root__";

const MAX_VISIBLE = 50;

export function ReclassPanel({
  csvOriginal,
  planValide,
  llmRawRows,
  busy,
  onApply,
  onCreateFolder,
  onRenameFolder,
  onDeleteFolder,
  planOriginal,
  initialSearch = "",
}: Props) {
  const [search, setSearch] = useState(initialSearch);
  // Recentrage : ODACEA n'a vocation qu'à rattraper les fichiers que l'IA a
  // laissés non classés (sinon orphelins à l'export) ; la retouche des items
  // déjà classés se fait dans Resip. Le panneau ouvre donc par défaut sur les
  // seuls non-classés. Le filtre reste désactivable (correction complète) ;
  // un « localiser » depuis les anomalies arrive avec une graine de recherche
  // et le désactive pour viser un item précis (souvent déjà classé).
  const [issuesOnly, setIssuesOnly] = useState(
    initialSearch.trim() === "",
  );
  const [edits, setEdits] = useState<Map<string, Edit>>(new Map());
  // Exemplaires en double retirés par l'archiviste (clés `rN`). Retirer la
  // ligne — et non la re-cibler — est la seule résolution d'un doublon : deux
  // lignes de même fichier portent le même ID, qu'importe leur dossier cible.
  const [removed, setRemoved] = useState<Set<string>>(new Set());

  // Dialogue de dossier. `create` : on crée le dossier puis on affecte la
  // ligne `rowKey`. `rename` : on renomme le dossier `tech`. `newParent`/
  // `newTitle` portent la saisie. `deleteTech` arme la confirmation de
  // suppression. Tout cela ne concerne que les dossiers créés à cette étape.
  const [dialog, setDialog] = useState<
    { mode: "create"; rowKey: string } | { mode: "rename"; tech: string } | null
  >(null);
  const [newParent, setNewParent] = useState<string>(ROOT_SENTINEL);
  const [newTitle, setNewTitle] = useState("");
  const [deleteTech, setDeleteTech] = useState<string | null>(null);

  // Suit un changement de filtre initial (clic « corriger » dans le tableau
  // des anomalies) sans écraser la frappe de l'utilisateur ensuite.
  const [prevSeed, setPrevSeed] = useState(initialSearch);
  if (initialSearch !== prevSeed) {
    setPrevSeed(initialSearch);
    setSearch(initialSearch);
    if (initialSearch.trim()) setIssuesOnly(false);
  }

  // Chemins des Items dans l'ordre du CSV source. Miroir assumé de l'ordre
  // déterministe de prepare_for_classement (backend) : Ref = position 1..N des
  // Items dans l'ordre des lignes. Sert à AFFICHER le chemin d'une ligne en
  // mode Ref et à fabriquer la Ref d'un non-classé rattaché — la réhydratation
  // autoritative Ref→Path reste côté Python à la finalisation.
  const itemPaths = useMemo(
    () =>
      csvOriginal
        .filter((r) => r["Content.DescriptionLevel"] === "Item")
        .map((r) => r["File"] ?? ""),
    [csvOriginal],
  );

  const refMode = llmRawRows.length > 0 && llmRawRows[0].Path === undefined;

  // Dossiers du plan, ordonnés, avec libellé lisible.
  const folders = useMemo(() => {
    const tree = parsePlanTree(planValide);
    const titles = parsePlanTitles(planValide);
    return Object.keys(tree)
      .sort((a, b) => {
        const ka = sortKey(a);
        const kb = sortKey(b);
        for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
          const d = (ka[i] ?? 0) - (kb[i] ?? 0);
          if (d !== 0) return d;
        }
        return a.localeCompare(b);
      })
      .map((name) => {
        const { number, label } = displayParts(name);
        const title = titles[name] ?? label;
        return { name, label: number ? `${number} ${title}` : title };
      });
  }, [planValide]);

  // Dossiers créés à cette étape = présents dans le plan courant mais absents du
  // plan d'origine. Eux seuls portent les icônes modifier/supprimer ; le reste
  // du plan (issu de l'audit) reste en lecture seule.
  const createdFolders = useMemo(() => {
    const original = new Set(Object.keys(parsePlanTree(planOriginal)));
    return new Set(
      folders.map((f) => f.name).filter((name) => !original.has(name)),
    );
  }, [folders, planOriginal]);

  // Titre descriptif courant d'un dossier (pour pré-remplir le renommage).
  const folderTitle = (tech: string) =>
    parsePlanTitles(planValide)[tech] ?? displayParts(tech).label;

  // Lignes éditables : sortie LLM (clé rN) + non-classés (clé u<path>).
  const entries = useMemo(() => {
    const pathOf = (row: LlmClassementRow): string => {
      if (row.Path !== undefined) return row.Path;
      const n = parseInt(row.Ref ?? "", 10);
      return (n >= 1 ? itemPaths[n - 1] : undefined) ?? `Ref ${row.Ref ?? "?"}`;
    };
    const classified = new Set(llmRawRows.map(pathOf));
    // Doublons de classement : un même fichier source recopié sur plusieurs
    // lignes LLM (classé dans deux dossiers) → deux lignes Item de même ID à la
    // conversion, rejetées par Resip. On marque chaque exemplaire pour que
    // l'archiviste retire les copies superflues (une seule cible permise).
    const pathCount = new Map<string, number>();
    for (const row of llmRawRows) {
      const p = pathOf(row);
      pathCount.set(p, (pathCount.get(p) ?? 0) + 1);
    }
    const rows = llmRawRows.map((row, i) => ({
      key: `r${i}`,
      path: pathOf(row),
      target: row.TargetFolder ?? "",
      title: row.NewTitle ?? "",
      unclassified: false,
      duplicate: (pathCount.get(pathOf(row)) ?? 0) > 1,
    }));
    for (const path of itemPaths) {
      if (!classified.has(path)) {
        rows.push({
          key: `u${path}`,
          path,
          target: "",
          title: path.split(/[\\/]/).pop() ?? path,
          unclassified: true,
          duplicate: false,
        });
      }
    }
    return rows;
  }, [llmRawRows, itemPaths]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    // Garde-fou : le filtre « problèmes » ne mord que s'il existe vraiment des
    // items à traiter (absents de la sortie LLM, ou classés en double). Quand les
    // fichiers manquants sont en fait des items mal aiguillés (présents dans la
    // sortie, mais cible hors plan / inconnue), il n'y a aucun « problème » au
    // sens strict — on retombe sur la liste complète plutôt qu'un tableau vide.
    const onlyIssues =
      issuesOnly && entries.some((e) => e.unclassified || e.duplicate);
    const filtered = entries.filter((e) => {
      if (onlyIssues && !e.unclassified && !e.duplicate) return false;
      if (!q) return true;
      const edit = edits.get(e.key);
      return (
        e.path.toLowerCase().includes(q) ||
        (edit?.NewTitle ?? e.title).toLowerCase().includes(q) ||
        (edit?.TargetFolder ?? e.target).toLowerCase().includes(q)
      );
    });
    // Regroupe en tête les exemplaires d'un même fichier classé en double, afin
    // que les copies à départager soient visibles côte à côte. Tri stable : les
    // autres lignes gardent leur ordre (sortie LLM puis non classés).
    return filtered
      .map((e, i) => ({ e, i }))
      .sort((a, b) => {
        const ad = a.e.duplicate ? 0 : 1;
        const bd = b.e.duplicate ? 0 : 1;
        if (ad !== bd) return ad - bd;
        if (a.e.duplicate && b.e.duplicate) {
          const c = a.e.path.localeCompare(b.e.path);
          if (c !== 0) return c;
        }
        return a.i - b.i;
      })
      .map(({ e }) => e);
  }, [entries, search, issuesOnly, edits]);

  const setEdit = (key: string, patch: Edit) => {
    setEdits((prev) => {
      const next = new Map(prev);
      next.set(key, { ...next.get(key), ...patch });
      return next;
    });
  };

  // Retire / rétablit un exemplaire en double (ligne `rN` de la sortie LLM).
  const toggleRemoved = (key: string) => {
    setRemoved((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  // Réaligne les affectations en cours après une mutation du plan : un dossier
  // renommé/décalé change de nom technique (remap), un dossier supprimé est
  // dé-affecté (`removed`) — sinon ces lignes viseraient un dossier disparu.
  const remapEdits = (remap: Map<string, string>, removed?: Set<string>) => {
    if (remap.size === 0 && !removed?.size) return;
    setEdits((prev) => {
      const next = new Map<string, Edit>();
      for (const [key, edit] of prev) {
        const target = edit.TargetFolder;
        if (target && removed?.has(target)) {
          // Dossier supprimé : on retire la cible ; on garde l'éventuel renommage.
          if (edit.NewTitle !== undefined) next.set(key, { NewTitle: edit.NewTitle });
          continue;
        }
        if (target && remap.has(target))
          next.set(key, { ...edit, TargetFolder: remap.get(target) });
        else next.set(key, edit);
      }
      return next;
    });
  };

  // Ouvre le dialogue de création pour la ligne `key` (parent par défaut = racine).
  const openCreateDialog = (key: string) => {
    setNewParent(ROOT_SENTINEL);
    setNewTitle("");
    setDialog({ mode: "create", rowKey: key });
  };

  // Ouvre le dialogue de renommage d'un dossier créé (libellé pré-rempli).
  const openRenameDialog = (tech: string) => {
    setNewTitle(folderTitle(tech));
    setDialog({ mode: "rename", tech });
  };

  // Valide le dialogue. Création : ajoute le dossier au plan puis affecte la
  // ligne en cours. Renommage : renomme et réaligne les affectations (remap).
  const confirmDialog = () => {
    if (!dialog || !newTitle.trim()) return;
    if (dialog.mode === "create") {
      const tech = onCreateFolder(
        newParent === ROOT_SENTINEL ? null : newParent,
        newTitle,
      );
      if (tech) setEdit(dialog.rowKey, { TargetFolder: tech });
    } else {
      const res = onRenameFolder(dialog.tech, newTitle);
      if (res) remapEdits(res.remap);
    }
    setDialog(null);
  };

  // Supprime un dossier créé (après confirmation) et dé-affecte ses fichiers.
  const confirmDelete = () => {
    if (!deleteTech) return;
    const res = onDeleteFolder(deleteTech);
    if (res) remapEdits(res.remap, new Set(res.removed));
    setDeleteTech(null);
  };

  const apply = async () => {
    const corrected: LlmClassementRow[] = [];
    llmRawRows.forEach((row, i) => {
      const key = `r${i}`;
      if (removed.has(key)) return; // exemplaire en double retiré par l'archiviste
      const edit = edits.get(key);
      corrected.push(edit ? { ...row, ...edit } : row);
    });
    for (const e of entries) {
      if (!e.unclassified) continue;
      const edit = edits.get(e.key);
      if (!edit?.TargetFolder) continue; // non rattaché : inchangé
      const newRow: LlmClassementRow = {
        TargetFolder: edit.TargetFolder,
        NewTitle: edit.NewTitle || e.title,
      };
      if (refMode) newRow.Ref = String(itemPaths.indexOf(e.path) + 1);
      else newRow.Path = e.path;
      corrected.push(newRow);
    }
    // Corrections validées : tout item que l'archiviste vient de
    // re-cibler (ou de classer pour la première fois), en métadonnées seules. Le
    // chemin source autoritatif (`itemPaths`) sert de garde — une Ref non résolue
    // (placeholder « Ref ? ») n'est jamais émise. La décision de réinjection est
    // prise par l'appelant ; ici on ne fait que collecter (transport).
    const corrections: CorrectionExample[] = [];
    for (const e of entries) {
      if (removed.has(e.key)) continue; // exemplaire retiré : pas une correction
      const edit = edits.get(e.key);
      if (!edit) continue;
      if (edit.TargetFolder === undefined && edit.NewTitle === undefined) continue;
      const targetFolder = edit.TargetFolder ?? e.target;
      if (!targetFolder || !itemPaths.includes(e.path)) continue;
      corrections.push({
        path: e.path,
        targetFolder,
        newTitle: edit.NewTitle ?? e.title,
      });
    }
    try {
      await onApply(corrected, corrections);
      setEdits(new Map());
      setRemoved(new Set());
    } catch {
      // Erreur déjà affichée par l'appelant (lastError) ; les corrections
      // restent en place pour réessayer.
    }
  };

  const editCount =
    removed.size +
    [...edits.entries()].filter(([key, e]) => {
      if (removed.has(key)) return false;
      if (key.startsWith("u")) return !!e.TargetFolder;
      return e.TargetFolder !== undefined || e.NewTitle !== undefined;
    }).length;
  const issuesCount = entries.filter(
    (e) => e.unclassified || e.duplicate,
  ).length;

  return (
    <div className="space-y-3">
      <p className="text-xs text-(--ink-500)">
        Rattachez à un dossier du plan les fichiers que l&apos;IA a laissés non
        classés, et retirez les exemplaires superflus des fichiers classés en
        double (un même fichier ne peut occuper qu&apos;un seul emplacement),
        puis re-finalisez : la conversion RESIP est recalculée en une passe, sans
        rappeler le modèle. La retouche fine des fichiers déjà classés se fait
        ensuite dans Resip.
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-52 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-(--ink-400)" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher un fichier, un dossier…"
            aria-label="Rechercher un fichier à corriger"
            className="h-8 pl-8 text-sm"
          />
        </div>
        {issuesCount > 0 && (
          <div className="flex items-center gap-2">
            <Switch
              id="reclass-issues"
              checked={issuesOnly}
              onCheckedChange={setIssuesOnly}
            />
            <Label htmlFor="reclass-issues" className="cursor-pointer text-xs">
              Problèmes uniquement ({issuesCount})
            </Label>
          </div>
        )}
      </div>

      <div className="overflow-x-auto rounded-md border border-(--ink-100)">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-(--ink-100) bg-(--paper-100) text-left text-(--ink-500)">
              <th scope="col" className="px-2 py-1.5 font-medium">
                Fichier source
              </th>
              <th scope="col" className="w-64 px-2 py-1.5 font-medium">
                Dossier cible
              </th>
              <th scope="col" className="w-56 px-2 py-1.5 font-medium">
                Nouveau titre
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.slice(0, MAX_VISIBLE).map((e) => {
              const edit = edits.get(e.key);
              const target = edit?.TargetFolder ?? e.target;
              const title = edit?.NewTitle ?? e.title;
              const modified =
                edit !== undefined &&
                (edit.TargetFolder !== undefined || edit.NewTitle !== undefined);
              const isRemoved = removed.has(e.key);
              return (
                <tr
                  key={e.key}
                  data-path={e.path}
                  className={
                    "border-b border-(--ink-100)/60 last:border-0 " +
                    (isRemoved ? "opacity-50 " : "") +
                    (modified || (e.duplicate && !isRemoved)
                      ? "bg-(--warning-500)/8"
                      : "")
                  }
                >
                  <td
                    className="max-w-72 truncate px-2 py-1 font-mono text-(--ink-700)"
                    title={e.path}
                  >
                    {e.unclassified && (
                      <span className="mr-1.5 rounded bg-(--danger-500)/10 px-1 py-0.5 text-[10px] font-medium text-(--danger-500)">
                        non classé
                      </span>
                    )}
                    {e.duplicate && (
                      <span className="mr-1.5 rounded bg-(--warning-500)/15 px-1 py-0.5 text-[10px] font-medium text-(--warning-500)">
                        classé en double
                      </span>
                    )}
                    <span className={isRemoved ? "line-through" : ""}>
                      {e.path}
                    </span>
                  </td>
                  <td className="px-2 py-1">
                    <div className="flex items-center gap-1">
                      <Select
                        value={target || undefined}
                        onValueChange={(v) =>
                          v === CREATE_SENTINEL
                            ? openCreateDialog(e.key)
                            : setEdit(e.key, { TargetFolder: v })
                        }
                        disabled={busy || isRemoved}
                      >
                        <SelectTrigger
                          size="sm"
                          className="h-7 w-full min-w-0 flex-1 font-mono text-xs"
                          aria-label={`Dossier cible de ${e.path}`}
                        >
                          <SelectValue placeholder="— choisir un dossier —" />
                        </SelectTrigger>
                        <SelectContent>
                          {/* Cible hors plan conservée en option (sinon Select vide). */}
                          {target && !folders.some((f) => f.name === target) && (
                            <SelectItem value={target}>
                              {target} (hors plan)
                            </SelectItem>
                          )}
                          {folders.map((f) => (
                            <SelectItem key={f.name} value={f.name}>
                              {f.label}
                            </SelectItem>
                          ))}
                          {/* Créer un dossier manquant dans le plan — le LLM
                              ne peut viser qu'un dossier existant du plan. */}
                          <SelectItem
                            value={CREATE_SENTINEL}
                            className="border-t border-(--ink-100) font-sans text-(--ink-700)"
                          >
                            <span className="flex items-center gap-1.5">
                              <FolderPlus className="h-3.5 w-3.5" />
                              Créer un dossier…
                            </span>
                          </SelectItem>
                        </SelectContent>
                      </Select>
                      {/* Modifier/supprimer — réservés aux dossiers créés ici ;
                          les dossiers du plan d'audit restent en lecture seule. */}
                      {target && createdFolders.has(target) && !isRemoved && (
                        <>
                          <FolderIconButton
                            label={`Renommer le dossier ${target}`}
                            icon={Pencil}
                            disabled={busy}
                            onClick={() => openRenameDialog(target)}
                          />
                          <FolderIconButton
                            label={`Supprimer le dossier ${target}`}
                            icon={Trash2}
                            destructive
                            disabled={busy}
                            onClick={() => setDeleteTech(target)}
                          />
                        </>
                      )}
                      {/* Doublon : retirer l'exemplaire superflu (ou le rétablir).
                          Seule résolution d'un ID dupliqué — un même fichier ne
                          peut occuper qu'un seul emplacement du SIP. */}
                      {e.duplicate &&
                        (isRemoved ? (
                          <FolderIconButton
                            label={`Rétablir l'affectation de ${e.path}`}
                            icon={RotateCcw}
                            disabled={busy}
                            onClick={() => toggleRemoved(e.key)}
                          />
                        ) : (
                          <FolderIconButton
                            label={`Retirer cet exemplaire en double de ${e.path}`}
                            icon={X}
                            destructive
                            disabled={busy}
                            onClick={() => toggleRemoved(e.key)}
                          />
                        ))}
                    </div>
                  </td>
                  <td className="px-2 py-1">
                    <Input
                      value={title}
                      onChange={(ev) =>
                        setEdit(e.key, { NewTitle: ev.target.value })
                      }
                      disabled={busy || isRemoved}
                      aria-label={`Nouveau titre de ${e.path}`}
                      className="h-7 font-mono text-xs"
                      spellCheck={false}
                    />
                  </td>
                </tr>
              );
            })}
            {visible.length === 0 && (
              <tr>
                <td colSpan={3} className="px-2 py-3 text-center text-(--ink-500)">
                  Aucun fichier ne correspond à la recherche.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {visible.length > MAX_VISIBLE && (
        <p className="text-xs text-(--ink-400)">
          {visible.length - MAX_VISIBLE} fichier(s) non affiché(s) — affinez la
          recherche.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={apply} disabled={busy || editCount === 0}>
          {busy ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
          )}
          Appliquer et re-finaliser ({editCount} modification
          {editCount >= 2 ? "s" : ""}) — sans appel IA
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setEdits(new Map());
            setRemoved(new Set());
          }}
          disabled={busy || editCount === 0}
        >
          <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
          Annuler les corrections
        </Button>
      </div>

      {/* Création / renommage d'un dossier du plan. À la création, le
          dossier est ajouté au plan validé (préfixe technique recalculé) et
          devient une cible comme une autre — jamais signalé « hors plan ». */}
      <Dialog open={dialog !== null} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {dialog?.mode === "rename"
                ? "Renommer le dossier"
                : "Créer un dossier dans le plan"}
            </DialogTitle>
            <DialogDescription>
              {dialog?.mode === "rename"
                ? "Le dossier est renommé dans le plan ; les fichiers qui lui sont rattachés suivent automatiquement."
                : "Le dossier est ajouté au plan validé (son numéro est calculé automatiquement d'après sa position), puis disponible comme cible de classement. Il n'est pas compté comme écart au plan."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {dialog?.mode === "create" && (
              <div className="space-y-1.5">
                <Label htmlFor="reclass-new-parent" className="text-xs">
                  Dossier parent
                </Label>
                <Select value={newParent} onValueChange={setNewParent}>
                  <SelectTrigger
                    id="reclass-new-parent"
                    size="sm"
                    className="w-full font-mono text-xs"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ROOT_SENTINEL} className="font-sans">
                      Premier niveau (racine)
                    </SelectItem>
                    {folders.map((f) => (
                      <SelectItem key={f.name} value={f.name}>
                        {f.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="reclass-new-title" className="text-xs">
                Nom du dossier
              </Label>
              <Input
                id="reclass-new-title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") confirmDialog();
                }}
                placeholder="ex. Ressources humaines"
                autoFocus
                className="h-8 text-sm"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>
              Annuler
            </Button>
            <Button onClick={confirmDialog} disabled={!newTitle.trim()}>
              {dialog?.mode === "rename" ? (
                <>
                  <Pencil className="mr-1.5 h-4 w-4" />
                  Renommer
                </>
              ) : (
                <>
                  <FolderPlus className="mr-1.5 h-4 w-4" />
                  Créer le dossier
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Suppression d'un dossier créé : confirmation explicite — elle dé-affecte
          les fichiers qui le visaient (ils redeviennent non classés). */}
      <ConfirmDialog
        open={deleteTech !== null}
        onOpenChange={(o) => !o && setDeleteTech(null)}
        title="Supprimer ce dossier ?"
        description="Le dossier est retiré du plan. Les fichiers qui lui étaient rattachés à cette étape redeviennent non classés et devront être réaffectés."
        confirmLabel="Supprimer"
        destructive
        onConfirm={confirmDelete}
      />
    </div>
  );
}

/** Petit bouton-icône (modifier/supprimer) accolé au Select de dossier cible. */
function FolderIconButton({
  label,
  icon: Icon,
  onClick,
  disabled,
  destructive,
}: {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  onClick: () => void;
  disabled?: boolean;
  destructive?: boolean;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-xs"
      className={
        "shrink-0 text-(--ink-400) hover:text-(--ink-700)" +
        (destructive ? " hover:text-(--danger-500)" : "")
      }
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
    >
      <Icon className="h-3.5 w-3.5" />
    </Button>
  );
}
