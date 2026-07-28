"use client";

import { useRef, useState } from "react";
import type { PlanModel, PlanNode, DropPosition } from "@/lib/csv/plan-edit";
import {
  parsePlanModel,
  applyPlanModel,
  moveNodeInModel,
  technicalName,
  slugify,
  validatePlanModel,
} from "@/lib/csv/plan-edit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  ArrowUp,
  ArrowDown,
  ChevronsLeft,
  ChevronsRight,
  Plus,
  Trash2,
  FolderPlus,
  Pencil,
  AlertTriangle,
  GripVertical,
} from "lucide-react";

// ── Éditeur d'arborescence structuré ─────────────────────────────────────────
// Le plan est réorganisé au glisser-déposer (déplacer un dossier n'importe où,
// la parenté se recalcule) et retouché au clic droit (renommer inline, ajouter
// un sous-dossier, supprimer). Chaque mutation re-sérialise le bloc
// « Arborescence technique » canonique (préfixes numériques recalculés) et le
// réinjecte dans le texte du plan via onChange — le reste du plan (approche,
// préconisations) est intact ; le Python re-dérive l'arbre à la conversion.

type Props = {
  planValide: string;
  onChange: (plan: string) => void;
  disabled?: boolean;
};

/** Chemin d'un nœud : indices successifs depuis model.nodes. */
type Path = number[];

/** Cible de dépôt courante (survol d'un glisser). */
type DropTarget = { path: Path; position: DropPosition };

const pathKey = (path: Path) => path.join(".");

/** Vrai si `prefix` est un préfixe de `path` (path dans le sous-arbre de prefix). */
function isPrefixPath(prefix: Path, path: Path): boolean {
  return (
    path.length >= prefix.length && prefix.every((v, i) => path[i] === v)
  );
}

function getSiblings(model: PlanModel, path: Path): PlanNode[] {
  let siblings = model.nodes;
  for (const idx of path.slice(0, -1)) siblings = siblings[idx].children;
  return siblings;
}

function getNode(model: PlanModel, path: Path): PlanNode {
  return getSiblings(model, path)[path[path.length - 1]];
}

export function PlanTreeEditor({ planValide, onChange, disabled }: Props) {
  const [model, setModel] = useState<PlanModel | null>(() =>
    parsePlanModel(planValide),
  );
  // Dernier plan émis par cet éditeur : si la prop revient identique, c'est
  // notre propre écho ; sinon c'est un changement externe (revert, édition
  // texte) → on re-parse. Ajustement pendant le rendu (pattern React) plutôt
  // que dans un effet.
  const [lastEmitted, setLastEmitted] = useState(planValide);
  const [prevPlan, setPrevPlan] = useState(planValide);
  if (planValide !== prevPlan) {
    setPrevPlan(planValide);
    if (planValide !== lastEmitted) {
      setLastEmitted(planValide);
      setModel(parsePlanModel(planValide));
    }
  }

  // Renommage inline : chemin du nœud en édition + instantané (titre/slug) pour
  // annuler à l'Échap. La saisie est commitée en direct (l'aperçu suit), le
  // snapshot n'est restauré que si l'utilisateur annule.
  const [editingPath, setEditingPath] = useState<Path | null>(null);
  const editSnapshot = useRef<{ title: string; slug: string } | null>(null);
  // Renommage inline de la racine (fonds) : même principe, sur rootTitle/rootSlug.
  const [editingRoot, setEditingRoot] = useState(false);
  const rootSnapshot = useRef<{ title: string; slug: string } | null>(null);

  // Glisser-déposer natif : source dans un ref (pas de re-rendu au dragstart),
  // cible de survol en state (indicateur de dépôt visible).
  const dragSrc = useRef<Path | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);

  if (!model) {
    return (
      <p className="text-sm text-(--ink-500)">
        Arborescence technique introuvable dans le plan — utilisez
        l&apos;édition en texte.
      </p>
    );
  }

  const commit = (next: PlanModel) => {
    setModel(next);
    const plan = applyPlanModel(planValide, next);
    setLastEmitted(plan);
    setPrevPlan(plan);
    onChange(plan);
  };

  const update = (mutate: (draft: PlanModel) => void) => {
    const draft = structuredClone(model);
    mutate(draft);
    commit(draft);
  };

  const newNode = (): PlanNode => ({
    title: "Nouveau dossier",
    slug: "Nouveau_dossier",
    children: [],
  });

  const patchNode = (path: Path, patch: Partial<PlanNode>) =>
    update((d) => Object.assign(getNode(d, path), patch));

  const removeNode = (path: Path) => {
    if (editingPath && pathKey(editingPath) === pathKey(path)) endEdit();
    update((d) => {
      getSiblings(d, path).splice(path[path.length - 1], 1);
    });
  };

  // Déplacements par bouton (alternative précise au glisser-déposer). Toute
  // mutation de structure sort d'un renommage en cours (les chemins changent).
  const moveSibling = (path: Path, delta: -1 | 1) => {
    endEdit();
    update((d) => {
      const siblings = getSiblings(d, path);
      const i = path[path.length - 1];
      const j = i + delta;
      if (j < 0 || j >= siblings.length) return;
      [siblings[i], siblings[j]] = [siblings[j], siblings[i]];
    });
  };

  /** Rétrograder : devient dernier enfant du frère précédent. */
  const indentNode = (path: Path) => {
    endEdit();
    update((d) => {
      const siblings = getSiblings(d, path);
      const i = path[path.length - 1];
      if (i === 0) return;
      const [node] = siblings.splice(i, 1);
      siblings[i - 1].children.push(node);
    });
  };

  /** Promouvoir : devient frère suivant de son parent. */
  const outdentNode = (path: Path) => {
    endEdit();
    update((d) => {
      if (path.length < 2) return;
      const parentPath = path.slice(0, -1);
      const siblings = getSiblings(d, path);
      const [node] = siblings.splice(path[path.length - 1], 1);
      const grandSiblings = getSiblings(d, parentPath);
      grandSiblings.splice(parentPath[parentPath.length - 1] + 1, 0, node);
    });
  };

  // Ajoute un dossier (sous `path`, ou premier niveau si null) puis le passe
  // aussitôt en renommage inline (l'utilisateur nomme son nouveau dossier). Le
  // nouveau nœud n'existe pas dans le `model` du rendu courant : on arme le
  // snapshot depuis ses valeurs par défaut (plutôt que via startEdit → getNode).
  const addChildAndEdit = (path: Path | null) => {
    const child = newNode();
    const newIndex = path ? getNode(model, path).children.length : model.nodes.length;
    update((d) => {
      (path ? getNode(d, path).children : d.nodes).push(child);
    });
    editSnapshot.current = { title: child.title, slug: child.slug };
    setEditingPath(path ? [...path, newIndex] : [newIndex]);
  };

  // ── Renommage inline ──────────────────────────────────────────────────────
  const startEdit = (path: Path) => {
    if (disabled) return;
    const node = getNode(model, path);
    editSnapshot.current = { title: node.title, slug: node.slug };
    setEditingRoot(false);
    setEditingPath(path);
  };
  const endEdit = () => {
    editSnapshot.current = null;
    setEditingPath(null);
  };
  const cancelEdit = () => {
    if (editingPath && editSnapshot.current)
      patchNode(editingPath, editSnapshot.current);
    endEdit();
  };

  // Renommage inline de la racine (titre du fonds + nom technique).
  const startEditRoot = () => {
    if (disabled) return;
    rootSnapshot.current = { title: model.rootTitle, slug: model.rootSlug };
    setEditingPath(null);
    setEditingRoot(true);
  };
  const endEditRoot = () => {
    rootSnapshot.current = null;
    setEditingRoot(false);
  };
  const cancelEditRoot = () => {
    if (rootSnapshot.current)
      commit({
        ...model,
        rootTitle: rootSnapshot.current.title,
        rootSlug: rootSnapshot.current.slug,
      });
    endEditRoot();
  };

  // ── Glisser-déposer ───────────────────────────────────────────────────────
  const onNodeDragStart = (e: React.DragEvent, path: Path) => {
    dragSrc.current = path;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", pathKey(path)); // requis par Firefox
  };

  const onNodeDragOver = (e: React.DragEvent, path: Path) => {
    const src = dragSrc.current;
    if (!src) return;
    // Dépôt interdit sur soi-même ou son propre sous-arbre : pas de preventDefault
    // → la rangée n'est pas une cible, et on retire l'indicateur d'une rangée
    // valide survolée précédemment.
    if (isPrefixPath(src, path)) {
      setDropTarget((prev) => (prev ? null : prev));
      return;
    }
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientY - rect.top) / rect.height;
    const position: DropPosition =
      ratio < 0.25 ? "before" : ratio > 0.75 ? "after" : "inside";
    setDropTarget((prev) =>
      prev && pathKey(prev.path) === pathKey(path) && prev.position === position
        ? prev
        : { path, position },
    );
  };

  const clearDrag = () => {
    dragSrc.current = null;
    setDropTarget(null);
  };

  const onNodeDrop = (e: React.DragEvent, path: Path) => {
    e.preventDefault();
    const src = dragSrc.current;
    if (!src || isPrefixPath(src, path)) return clearDrag();
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientY - rect.top) / rect.height;
    const position: DropPosition =
      ratio < 0.25 ? "before" : ratio > 0.75 ? "after" : "inside";
    const next = moveNodeInModel(model, src, path, position);
    clearDrag();
    if (next) {
      endEdit(); // les chemins changent : on sort d'un éventuel renommage
      commit(next);
    }
  };

  // Validation live : non bloquante, recalculée à chaque mutation.
  const issues = validatePlanModel(model);
  const invalidTechs = new Set(issues.map((i) => i.tech).filter(Boolean));
  const rootInvalid = issues.some((i) => i.tech === "");

  return (
    <div className="space-y-2 text-sm">
      {/* Racine du fonds. Le label « Fonds — » est ajouté à la sérialisation :
          on le montre en préfixe non éditable pour que le champ ne contienne que
          l'intitulé nu (sinon « Fonds — » s'accumulerait à chaque édition). Même
          principe que les nœuds : libellé + renommage inline + clic droit (pas de
          suppression ni de glisser — c'est le conteneur du fonds). */}
      <ContextMenu>
        <ContextMenuTrigger asChild disabled={disabled}>
          <div
            onDoubleClick={() => !editingRoot && startEditRoot()}
            onKeyDown={(e) => {
              if (!editingRoot && e.key === "F2") {
                e.preventDefault();
                startEditRoot();
              }
            }}
            tabIndex={editingRoot ? -1 : 0}
            className={
              "flex flex-wrap items-center gap-1.5 rounded-md px-2 py-1 hover:bg-[rgba(120,120,120,0.06)] focus-visible:outline-2 focus-visible:outline-(--ink-400) " +
              (editingRoot ? "" : "cursor-pointer")
            }
          >
            <span className="font-semibold text-(--ink-500)" aria-hidden>
              Fonds —
            </span>
            {editingRoot ? (
              <>
                <Input
                  autoFocus
                  onFocus={(e) => e.target.select()}
                  value={model.rootTitle}
                  onChange={(e) =>
                    commit({ ...model, rootTitle: e.target.value })
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") endEditRoot();
                    else if (e.key === "Escape") cancelEditRoot();
                  }}
                  onBlur={(e) => {
                    if (
                      !e.currentTarget.parentElement?.contains(
                        e.relatedTarget as Node,
                      )
                    )
                      endEditRoot();
                  }}
                  placeholder="Intitulé du fonds"
                  aria-label="Intitulé du fonds"
                  disabled={disabled}
                  className="h-7 w-auto min-w-40 flex-1 font-semibold"
                />
                <span className="text-(--ink-300)">→</span>
                <SlugInput
                  value={model.rootSlug}
                  onChange={(v) => commit({ ...model, rootSlug: v })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") endEditRoot();
                    else if (e.key === "Escape") cancelEditRoot();
                  }}
                  ariaLabel="Nom technique de la racine"
                  disabled={disabled}
                  invalid={rootInvalid}
                />
              </>
            ) : (
              <>
                <span
                  className={
                    "flex-1 font-semibold " +
                    (rootInvalid ? "text-(--danger-500)" : "text-(--ink-900)")
                  }
                >
                  {model.rootTitle || (
                    <span className="italic text-(--ink-400)">
                      (intitulé du fonds)
                    </span>
                  )}
                </span>
                <span className="font-mono text-[11px] text-(--ink-300)">
                  {model.rootSlug}/
                </span>
              </>
            )}
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent>
          <ContextMenuItem onSelect={startEditRoot}>
            <Pencil className="h-3.5 w-3.5" />
            Renommer le fonds
          </ContextMenuItem>
          <ContextMenuItem onSelect={() => addChildAndEdit(null)}>
            <FolderPlus className="h-3.5 w-3.5" />
            Ajouter un dossier
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>

      <div className="ml-3.25 border-l-[1.5px] border-[rgba(120,120,120,0.2)] pl-3">
        {model.nodes.map((node, i) => (
          <EditorNode
            key={i}
            node={node}
            path={[i]}
            numberParts={[i + 1]}
            siblingCount={model.nodes.length}
            invalidTechs={invalidTechs}
            disabled={disabled}
            editingPath={editingPath}
            dropTarget={dropTarget}
            onPatch={patchNode}
            onAddChild={addChildAndEdit}
            onRemove={removeNode}
            onMove={moveSibling}
            onIndent={indentNode}
            onOutdent={outdentNode}
            onStartEdit={startEdit}
            onEndEdit={endEdit}
            onCancelEdit={cancelEdit}
            onDragStart={onNodeDragStart}
            onDragOver={onNodeDragOver}
            onDrop={onNodeDrop}
            onDragEnd={clearDrag}
          />
        ))}
      </div>

      {/* Validation live du plan — annoncée aux lecteurs d'écran. */}
      {issues.length > 0 && (
        <div
          role="status"
          aria-live="polite"
          className="rounded-md border border-(--warning-500)/40 bg-(--warning-500)/5 px-3 py-2"
        >
          <p className="flex items-center gap-1.5 text-xs font-medium text-(--ink-700)">
            <AlertTriangle className="h-3.5 w-3.5 text-(--warning-500)" />
            {issues.length === 1
              ? "1 problème détecté dans le plan"
              : `${issues.length} problèmes détectés dans le plan`}
          </p>
          <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs text-(--ink-600)">
            {issues.map((issue, i) => (
              <li key={i}>{issue.message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-center justify-between gap-2 pt-1">
        <Button
          variant="outline"
          size="sm"
          onClick={() => addChildAndEdit(null)}
          disabled={disabled}
        >
          <FolderPlus className="mr-1.5 h-3.5 w-3.5" />
          Ajouter un dossier
        </Button>
        <p className="text-xs text-(--ink-400)">
          Glissez un dossier pour le déplacer ; clic droit pour renommer, ajouter
          ou supprimer
        </p>
      </div>
    </div>
  );
}

function EditorNode({
  node,
  path,
  numberParts,
  siblingCount,
  invalidTechs,
  disabled,
  editingPath,
  dropTarget,
  onPatch,
  onAddChild,
  onRemove,
  onMove,
  onIndent,
  onOutdent,
  onStartEdit,
  onEndEdit,
  onCancelEdit,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}: {
  node: PlanNode;
  path: Path;
  numberParts: number[];
  siblingCount: number;
  invalidTechs: Set<string>;
  disabled?: boolean;
  editingPath: Path | null;
  dropTarget: DropTarget | null;
  onPatch: (path: Path, patch: Partial<PlanNode>) => void;
  onAddChild: (path: Path) => void;
  onRemove: (path: Path) => void;
  onMove: (path: Path, delta: -1 | 1) => void;
  onIndent: (path: Path) => void;
  onOutdent: (path: Path) => void;
  onStartEdit: (path: Path) => void;
  onEndEdit: () => void;
  onCancelEdit: () => void;
  onDragStart: (e: React.DragEvent, path: Path) => void;
  onDragOver: (e: React.DragEvent, path: Path) => void;
  onDrop: (e: React.DragEvent, path: Path) => void;
  onDragEnd: () => void;
}) {
  const index = path[path.length - 1];
  const number = numberParts.join(".");
  const tech = technicalName(numberParts, node.slug);
  const isEditing = editingPath !== null && pathKey(editingPath) === pathKey(path);
  // Le slug suit le titre tant que l'utilisateur ne l'a pas édité lui-même
  // (slug encore égal au slugifié du titre courant).
  const slugFollowsTitle = node.slug === slugify(node.title);
  const invalid = invalidTechs.has(tech);

  const drop =
    dropTarget && pathKey(dropTarget.path) === pathKey(path)
      ? dropTarget.position
      : null;

  return (
    <div>
      <ContextMenu>
        <ContextMenuTrigger asChild disabled={disabled}>
          <div
            data-folder={tech}
            draggable={!disabled && !isEditing}
            onDragStart={(e) => onDragStart(e, path)}
            onDragOver={(e) => onDragOver(e, path)}
            onDrop={(e) => onDrop(e, path)}
            onDragEnd={onDragEnd}
            onDoubleClick={() => !isEditing && onStartEdit(path)}
            onKeyDown={(e) => {
              if (!isEditing && e.key === "F2") {
                e.preventDefault();
                onStartEdit(path);
              }
            }}
            tabIndex={isEditing ? -1 : 0}
            className={
              "group relative flex flex-wrap items-center gap-1.5 rounded-md px-2 py-1 hover:bg-[rgba(120,120,120,0.06)] focus-visible:outline-2 focus-visible:outline-(--ink-400) " +
              (isEditing ? "" : "cursor-grab ") +
              (drop === "inside" ? "bg-accent/40 ring-1 ring-accent" : "")
            }
          >
            {/* Indicateurs de dépôt (avant / après) — sans décalage de mise en page. */}
            {drop === "before" && (
              <span className="pointer-events-none absolute inset-x-1 top-0 h-0.5 rounded bg-(--ink-700)" />
            )}
            {drop === "after" && (
              <span className="pointer-events-none absolute inset-x-1 bottom-0 h-0.5 rounded bg-(--ink-700)" />
            )}

            {!isEditing && (
              <GripVertical
                className="h-3.5 w-3.5 shrink-0 text-(--ink-300) opacity-0 transition-opacity group-hover:opacity-100"
                aria-hidden
              />
            )}
            <span className="min-w-6.5 text-xs font-bold text-(--ink-500)">
              {number}
            </span>

            {isEditing ? (
              <>
                <Input
                  autoFocus
                  onFocus={(e) => e.target.select()}
                  value={node.title}
                  onChange={(e) =>
                    onPatch(
                      path,
                      slugFollowsTitle
                        ? { title: e.target.value, slug: slugify(e.target.value) }
                        : { title: e.target.value },
                    )
                  }
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onEndEdit();
                    else if (e.key === "Escape") onCancelEdit();
                  }}
                  onBlur={(e) => {
                    // Ne pas sortir si le focus passe au champ slug de la même
                    // rangée (frère dans le div de rangée = parent direct).
                    if (
                      !e.currentTarget.parentElement?.contains(
                        e.relatedTarget as Node,
                      )
                    )
                      onEndEdit();
                  }}
                  placeholder="Titre descriptif"
                  aria-label={`Titre du dossier ${number}`}
                  disabled={disabled}
                  className="h-7 w-auto min-w-36 flex-1"
                />
                <span className="text-(--ink-300)">→</span>
                <SlugInput
                  value={node.slug}
                  prefix={`${numberParts.join("-")}_`}
                  onChange={(v) => onPatch(path, { slug: v })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onEndEdit();
                    else if (e.key === "Escape") onCancelEdit();
                  }}
                  ariaLabel={`Nom technique du dossier ${number}`}
                  disabled={disabled}
                  invalid={invalid}
                />
              </>
            ) : (
              <>
                <span
                  className={
                    "flex-1 font-medium " +
                    (invalid ? "text-(--danger-500)" : "text-(--ink-900)")
                  }
                >
                  {node.title || (
                    <span className="italic text-(--ink-400)">
                      (sans titre)
                    </span>
                  )}
                </span>
                <span className="font-mono text-[11px] text-(--ink-300)">
                  {tech}
                </span>
                {/* Boutons d'action au survol : alternative précise au glisser. */}
                <span
                  className="flex items-center opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100"
                  role="group"
                  aria-label={`Actions sur le dossier ${number}`}
                >
                  <NodeAction
                    label="Monter"
                    icon={ArrowUp}
                    disabled={disabled || index === 0}
                    onClick={() => onMove(path, -1)}
                  />
                  <NodeAction
                    label="Descendre"
                    icon={ArrowDown}
                    disabled={disabled || index === siblingCount - 1}
                    onClick={() => onMove(path, 1)}
                  />
                  <NodeAction
                    label="Rétrograder (sous le dossier précédent)"
                    icon={ChevronsRight}
                    disabled={disabled || index === 0}
                    onClick={() => onIndent(path)}
                  />
                  <NodeAction
                    label="Promouvoir (au niveau du parent)"
                    icon={ChevronsLeft}
                    disabled={disabled || path.length < 2}
                    onClick={() => onOutdent(path)}
                  />
                  <NodeAction
                    label="Renommer"
                    icon={Pencil}
                    disabled={disabled}
                    onClick={() => onStartEdit(path)}
                  />
                  <NodeAction
                    label="Ajouter un sous-dossier"
                    icon={Plus}
                    disabled={disabled}
                    onClick={() => onAddChild(path)}
                  />
                  <NodeAction
                    label={
                      node.children.length > 0
                        ? "Supprimer (avec ses sous-dossiers)"
                        : "Supprimer"
                    }
                    icon={Trash2}
                    destructive
                    disabled={disabled}
                    onClick={() => onRemove(path)}
                  />
                </span>
              </>
            )}
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent>
          <ContextMenuItem onSelect={() => onStartEdit(path)}>
            <Pencil className="h-3.5 w-3.5" />
            Renommer
          </ContextMenuItem>
          <ContextMenuItem onSelect={() => onAddChild(path)}>
            <FolderPlus className="h-3.5 w-3.5" />
            Ajouter un sous-dossier
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem
            variant="destructive"
            onSelect={() => onRemove(path)}
          >
            <Trash2 className="h-3.5 w-3.5" />
            {node.children.length > 0 ? "Supprimer (avec ses sous-dossiers)" : "Supprimer"}
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>

      {node.children.length > 0 && (
        <div className="ml-3.25 mt-0.5 border-l-[1.5px] border-[rgba(120,120,120,0.2)] pl-3">
          {node.children.map((child, i) => (
            <EditorNode
              key={i}
              node={child}
              path={[...path, i]}
              numberParts={[...numberParts, i + 1]}
              siblingCount={node.children.length}
              invalidTechs={invalidTechs}
              disabled={disabled}
              editingPath={editingPath}
              dropTarget={dropTarget}
              onPatch={onPatch}
              onAddChild={onAddChild}
              onRemove={onRemove}
              onMove={onMove}
              onIndent={onIndent}
              onOutdent={onOutdent}
              onStartEdit={onStartEdit}
              onEndEdit={onEndEdit}
              onCancelEdit={onCancelEdit}
              onDragStart={onDragStart}
              onDragOver={onDragOver}
              onDrop={onDrop}
              onDragEnd={onDragEnd}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function NodeAction({
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
        "text-(--ink-400) hover:text-(--ink-700)" +
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

function SlugInput({
  value,
  prefix,
  onChange,
  onKeyDown,
  ariaLabel,
  disabled,
  invalid,
}: {
  value: string;
  prefix?: string;
  onChange: (v: string) => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  ariaLabel: string;
  disabled?: boolean;
  invalid?: boolean;
}) {
  return (
    <span className="flex items-center font-mono text-xs text-(--ink-500)">
      {prefix && <span aria-hidden>{prefix}</span>}
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        aria-label={ariaLabel}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        className="h-7 w-56 px-2 font-mono text-xs"
        spellCheck={false}
      />
      <span aria-hidden>/</span>
    </span>
  );
}
