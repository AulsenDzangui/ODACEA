"use client";

import { useMemo, useState } from "react";
import {
  parsePlanTree,
  parsePlanTitles,
  parsePlanRootTitle,
  displayParts,
  sortKey,
} from "@/lib/csv/plan-tree";

type Props = {
  planValide: string;
};

export function PlanTree({ planValide }: Props) {
  const tree = useMemo(() => parsePlanTree(planValide), [planValide]);
  const titles = useMemo(() => parsePlanTitles(planValide), [planValide]);
  const rootTitle = useMemo(() => parsePlanRootTitle(planValide), [planValide]);
  const childrenMap = useMemo(() => {
    const map = new Map<string | null, string[]>();
    for (const [folder, parent] of Object.entries(tree)) {
      const key = parent;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(folder);
    }
    for (const list of map.values()) {
      list.sort((a, b) => {
        const ka = sortKey(a);
        const kb = sortKey(b);
        for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
          const da = ka[i] ?? 0;
          const db = kb[i] ?? 0;
          if (da !== db) return da - db;
        }
        return 0;
      });
    }
    return map;
  }, [tree]);

  if (Object.keys(tree).length === 0) {
    return (
      <p className="text-sm text-(--ink-500)">
        Arborescence technique introuvable dans le plan.
      </p>
    );
  }

  const roots = childrenMap.get(null) ?? [];

  const rootNodes = roots.map((r) => (
    <TreeNode
      key={r}
      name={r}
      childrenMap={childrenMap}
      titles={titles}
      depth={rootTitle ? 1 : 0}
    />
  ));

  return (
    <div className="text-sm">
      {rootTitle ? <RootNode title={rootTitle}>{rootNodes}</RootNode> : rootNodes}
    </div>
  );
}

// Nœud racine : l'intitulé du fonds (ligne « Fonds — … → Dossier_racine/ »).
// N'est pas un vrai dossier de l'arbre — il englobe et rend repliables les
// dossiers de premier niveau.
function RootNode({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.25 text-left transition-colors hover:bg-[rgba(120,120,120,0.1)]"
        aria-expanded={open}
      >
        <span className="text-[14px] leading-none">{open ? "📂" : "📁"}</span>
        <span className="flex-1 font-semibold text-(--ink-900)">
          Fonds — {title}
        </span>
      </button>
      {open && (
        <div className="ml-3.25 mt-0.5 border-l-[1.5px] border-[rgba(120,120,120,0.2)] pl-4">
          {children}
        </div>
      )}
    </div>
  );
}

function TreeNode({
  name,
  childrenMap,
  titles,
  depth,
}: {
  name: string;
  childrenMap: Map<string | null, string[]>;
  titles: Record<string, string>;
  depth: number;
}) {
  const [open, setOpen] = useState(true);
  const kids = childrenMap.get(name) ?? [];
  const { number, label: derivedLabel } = displayParts(name);
  // Titre descriptif porté par le plan fusionné ; fallback sur le label dérivé
  // du nom technique (plan à l'ancien format).
  const label = titles[name] ?? derivedLabel;
  const hasChildren = kids.length > 0;

  return (
    <div style={{ paddingLeft: depth === 0 ? 0 : 16 }}>
      <button
        type="button"
        onClick={() => hasChildren && setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.25 text-left transition-colors hover:bg-[rgba(120,120,120,0.1)]"
        aria-expanded={hasChildren ? open : undefined}
      >
        <span className="text-[14px] leading-none">
          {hasChildren ? (open ? "📂" : "📁") : "📁"}
        </span>
        {number && (
          <span className="min-w-6.5 text-xs font-bold text-(--ink-500)">
            {number}
          </span>
        )}
        <span className="flex-1 font-medium text-(--ink-900)">{label}</span>
        <span className="text-[11px] text-(--ink-300)">{name}</span>
      </button>
      {open && hasChildren && (
        <div className="ml-3.25 mt-0.5 border-l-[1.5px] border-[rgba(120,120,120,0.2)] pl-4">
          {kids.map((k) => (
            <TreeNode
              key={k}
              name={k}
              childrenMap={childrenMap}
              titles={titles}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}
