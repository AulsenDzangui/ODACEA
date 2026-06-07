"use client";

import { useState } from "react";
import type { CsvTreeNode } from "@/lib/csv/csv-tree";

type Props = {
  nodes: CsvTreeNode[];
};

export function CsvTreeView({ nodes }: Props) {
  if (nodes.length === 0) {
    return (
      <p className="text-sm text-(--ink-500)">Aucune donnée à afficher.</p>
    );
  }
  return (
    <div className="text-sm">
      {nodes.map((node) => (
        <CsvNode key={node.id} node={node} />
      ))}
    </div>
  );
}

function CsvNode({ node }: { node: CsvTreeNode }) {
  const [open, setOpen] = useState(true);
  const hasChildren = node.children.length > 0;

  if (!node.isFolder) {
    return (
      <div className="flex items-center gap-1.5 rounded-md px-2 py-1 text-(--ink-600)">
        <span className="text-[13px] leading-none opacity-50">📄</span>
        <span className="flex-1 truncate">{node.title}</span>
      </div>
    );
  }

  return (
    <div>
      <button
        type="button"
        onClick={() => hasChildren && setOpen((v) => !v)}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.25 text-left transition-colors hover:bg-[rgba(120,120,120,0.1)]"
        aria-expanded={hasChildren ? open : undefined}
      >
        <span className="text-[14px] leading-none">
          {hasChildren ? (open ? "📂" : "📁") : "📁"}
        </span>
        <span className="flex-1 font-medium text-(--ink-900) truncate">
          {node.title}
        </span>
      </button>
      {open && hasChildren && (
        <div className="ml-3.25 mt-0.5 border-l-[1.5px] border-[rgba(120,120,120,0.2)] pl-4">
          {node.children.map((child) => (
            <CsvNode key={child.id} node={child} />
          ))}
        </div>
      )}
    </div>
  );
}
