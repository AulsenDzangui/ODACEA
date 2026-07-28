"use client";

import { useState } from "react";
import type { CsvTreeNode } from "@/lib/csv/csv-tree";
import { searchCsvTree } from "@/lib/csv/csv-tree";

type Props = {
  nodes: CsvTreeNode[];
  /** Recherche : seules les branches contenant une correspondance sont
   *  affichées, dossiers dépliés, fichiers trouvés surlignés, trajet
   *  (ancêtres) marqué. */
  query?: string;
};

export function CsvTreeView({ nodes, query = "" }: Props) {
  const match = searchCsvTree(nodes, query);
  const filtering = query.trim().length > 0;

  if (nodes.length === 0) {
    return (
      <p className="text-sm text-(--ink-500)">Aucune donnée à afficher.</p>
    );
  }
  if (filtering && match.withMatch.size === 0) {
    return (
      <p className="px-2 py-1 text-sm text-(--ink-500)">
        Aucun fichier ne correspond à la recherche.
      </p>
    );
  }
  return (
    <div className="text-sm">
      {nodes.map((node) => (
        <CsvNode
          key={node.id}
          node={node}
          filtering={filtering}
          matched={match.matched}
          withMatch={match.withMatch}
        />
      ))}
    </div>
  );
}

function CsvNode({
  node,
  filtering,
  matched,
  withMatch,
}: {
  node: CsvTreeNode;
  filtering: boolean;
  matched: Set<string>;
  withMatch: Set<string>;
}) {
  const [open, setOpen] = useState(true);
  const hasChildren = node.children.length > 0;

  if (filtering && !withMatch.has(node.id)) return null;
  const isMatch = matched.has(node.id);
  // Trajet du fichier trouvé : ancêtre d'une correspondance, sans l'être lui-même.
  const onPath = filtering && !isMatch && withMatch.has(node.id);
  const highlight = isMatch
    ? " bg-(--warning-500)/20 font-medium text-(--ink-900)"
    : "";

  if (!node.isFolder) {
    return (
      <div
        className={
          "flex items-center gap-1.5 rounded-md px-2 py-1 text-(--ink-600)" +
          highlight
        }
      >
        <span className="text-[13px] leading-none opacity-50">📄</span>
        <span className="flex-1 truncate" title={node.file || undefined}>
          {node.title}
        </span>
      </div>
    );
  }

  // En recherche : tout le trajet est déplié d'office.
  const effectiveOpen = filtering ? true : open;

  return (
    <div>
      <button
        type="button"
        onClick={() => hasChildren && !filtering && setOpen((v) => !v)}
        className={
          "flex w-full items-center gap-1.5 rounded-md px-2 py-1.25 text-left transition-colors hover:bg-[rgba(120,120,120,0.1)]" +
          highlight
        }
        aria-expanded={hasChildren ? effectiveOpen : undefined}
      >
        <span className="text-[14px] leading-none">
          {hasChildren ? (effectiveOpen ? "📂" : "📁") : "📁"}
        </span>
        <span
          className={
            "flex-1 truncate font-medium " +
            (onPath ? "text-(--graphite-700) underline decoration-(--warning-500)/60 decoration-2 underline-offset-3" : "text-(--ink-900)")
          }
        >
          {node.title}
        </span>
      </button>
      {effectiveOpen && hasChildren && (
        <div
          className={
            "ml-3.25 mt-0.5 border-l-[1.5px] pl-4 " +
            (onPath
              ? "border-(--warning-500)/50"
              : "border-[rgba(120,120,120,0.2)]")
          }
        >
          {node.children.map((child) => (
            <CsvNode
              key={child.id}
              node={child}
              filtering={filtering}
              matched={matched}
              withMatch={withMatch}
            />
          ))}
        </div>
      )}
    </div>
  );
}
