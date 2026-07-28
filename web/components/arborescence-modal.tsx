"use client";

import { useMemo, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { buildCsvTree, csvTreeStats, searchCsvTree } from "@/lib/csv/csv-tree";
import { CsvTreeView } from "@/components/csv-tree-view";
import type { SedaRow, ResipResult } from "@/lib/csv/types";
import { Search } from "lucide-react";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  csvOriginal: SedaRow[];
  csvFinal: ResipResult;
};

// ── Vue avant/après ──────────────────────────────────────────────────────────
// Arborescence source et arborescence cible côte à côte ; une recherche
// commune surligne le fichier trouvé et son trajet dans chacune des deux vues
// — pour vérifier d'un coup d'œil d'où vient et où va un document.

export function ArborescenceModal({
  open,
  onOpenChange,
  csvOriginal,
  csvFinal,
}: Props) {
  const [query, setQuery] = useState("");

  const treeOriginal = useMemo(() => buildCsvTree(csvOriginal), [csvOriginal]);
  const treeFinal = useMemo(
    () => buildCsvTree(csvFinal.rows),
    [csvFinal.rows],
  );
  const statsOriginal = useMemo(
    () => csvTreeStats(csvOriginal),
    [csvOriginal],
  );
  const statsFinal = useMemo(
    () => csvTreeStats(csvFinal.rows),
    [csvFinal.rows],
  );
  const nFoundOriginal = useMemo(
    () => searchCsvTree(treeOriginal, query).matched.size,
    [treeOriginal, query],
  );
  const nFoundFinal = useMemo(
    () => searchCsvTree(treeFinal, query).matched.size,
    [treeFinal, query],
  );
  const searching = query.trim().length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-6xl">
        <DialogHeader className="px-4 pt-4 pb-2">
          <DialogTitle>Arborescence avant / après</DialogTitle>
        </DialogHeader>

        <div className="px-4 pb-3">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-(--ink-400)" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Rechercher un fichier — son trajet est surligné dans les deux vues"
              aria-label="Rechercher un fichier dans les deux arborescences"
              className="h-8 pl-8 text-sm"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-0 border-t border-(--ink-100) md:grid-cols-2 md:divide-x md:divide-(--ink-100)">
          <TreePane
            heading="Avant classement"
            stats={statsOriginal}
            found={searching ? nFoundOriginal : null}
          >
            <CsvTreeView nodes={treeOriginal} query={query} />
          </TreePane>
          <TreePane
            heading="Après classement"
            stats={statsFinal}
            found={searching ? nFoundFinal : null}
          >
            <CsvTreeView nodes={treeFinal} query={query} />
          </TreePane>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TreePane({
  heading,
  stats,
  found,
  children,
}: {
  heading: string;
  stats: { folders: number; items: number };
  found: number | null;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={heading} className="min-w-0">
      <div className="flex items-baseline justify-between gap-2 px-4 py-2">
        <h3 className="text-sm font-semibold text-(--ink-900)">{heading}</h3>
        <p className="text-xs text-(--ink-500)">
          {found !== null
            ? `${found} résultat${found >= 2 ? "s" : ""}`
            : `${stats.folders} dossiers · ${stats.items} fichiers`}
        </p>
      </div>
      <ScrollArea className="h-[56vh] border-t border-(--ink-100)/60">
        <div className="px-3 py-1">{children}</div>
      </ScrollArea>
    </section>
  );
}
