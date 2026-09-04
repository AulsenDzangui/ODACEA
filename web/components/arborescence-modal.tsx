"use client";

import { useMemo, useRef, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { buildCsvTree, csvTreeStats, searchCsvTree } from "@/lib/csv/csv-tree";
import { CsvTreeView, type CsvTreeViewHandle } from "@/components/csv-tree-view";
import type { SedaRow } from "@/lib/csv/types";
import { ChevronsDownUp, ChevronsUpDown, Search } from "lucide-react";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  rowsOriginal: SedaRow[];
  /** Lignes du SIP **telles qu'exportées** (options d'export de titre déjà
   *  appliquées par l'appelant, cf. `applyExportTitleChoices`) — l'aperçu doit
   *  montrer les titres du CSV téléchargé et de la copie physique, pas les
   *  titres bruts du finalize. */
  rowsFinal: SedaRow[];
};

// ── Vue avant/après ──────────────────────────────────────────────────────────
// Arborescence source et arborescence cible côte à côte ; une recherche
// commune surligne le fichier trouvé et son trajet dans chacune des deux vues
// — pour vérifier d'un coup d'œil d'où vient et où va un document. Le
// container occupe (presque) tout l'écran et chaque volet a ses propres
// boutons plier/déplier tout, la profondeur d'un vrac réel dépassant vite ce
// qu'une fenêtre modale de taille normale peut montrer utilement.

export function ArborescenceModal({
  open,
  onOpenChange,
  rowsOriginal,
  rowsFinal,
}: Props) {
  const [query, setQuery] = useState("");
  const treeRefOriginal = useRef<CsvTreeViewHandle>(null);
  const treeRefFinal = useRef<CsvTreeViewHandle>(null);

  const treeOriginal = useMemo(() => buildCsvTree(rowsOriginal), [rowsOriginal]);
  const treeFinal = useMemo(() => buildCsvTree(rowsFinal), [rowsFinal]);
  const statsOriginal = useMemo(() => csvTreeStats(rowsOriginal), [rowsOriginal]);
  const statsFinal = useMemo(() => csvTreeStats(rowsFinal), [rowsFinal]);
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
      <DialogContent className="flex h-[92vh] w-[96vw] max-w-400 flex-col gap-0 overflow-hidden p-0 sm:max-w-[96vw]">
        <DialogHeader className="shrink-0 px-4 pt-4 pb-2">
          <DialogTitle>Arborescence avant / après</DialogTitle>
        </DialogHeader>

        <div className="shrink-0 px-4 pb-3">
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

        <div className="grid min-h-0 flex-1 auto-rows-fr grid-cols-1 gap-0 border-t border-(--ink-100) md:grid-cols-2 md:divide-x md:divide-(--ink-100)">
          <TreePane
            heading="Avant classement"
            stats={statsOriginal}
            found={searching ? nFoundOriginal : null}
            onExpandAll={() => treeRefOriginal.current?.expandAll()}
            onCollapseAll={() => treeRefOriginal.current?.collapseAll()}
          >
            <CsvTreeView ref={treeRefOriginal} nodes={treeOriginal} query={query} />
          </TreePane>
          <TreePane
            heading="Après classement"
            stats={statsFinal}
            found={searching ? nFoundFinal : null}
            onExpandAll={() => treeRefFinal.current?.expandAll()}
            onCollapseAll={() => treeRefFinal.current?.collapseAll()}
          >
            <CsvTreeView ref={treeRefFinal} nodes={treeFinal} query={query} />
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
  onExpandAll,
  onCollapseAll,
  children,
}: {
  heading: string;
  stats: { folders: number; items: number };
  found: number | null;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={heading} className="flex min-h-0 min-w-0 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 px-4 py-2">
        <h3 className="text-sm font-semibold text-(--ink-900)">{heading}</h3>
        <div className="flex items-center gap-2">
          <p className="text-xs text-(--ink-500)">
            {found !== null
              ? `${found} résultat${found >= 2 ? "s" : ""}`
              : `${stats.folders} dossiers · ${stats.items} fichiers`}
          </p>
          <div className="flex items-center gap-0.5">
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              title="Tout déplier"
              aria-label={`Tout déplier — ${heading}`}
              onClick={onExpandAll}
            >
              <ChevronsUpDown />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              title="Tout replier"
              aria-label={`Tout replier — ${heading}`}
              onClick={onCollapseAll}
            >
              <ChevronsDownUp />
            </Button>
          </div>
        </div>
      </div>
      <ScrollArea className="min-h-0 flex-1 border-t border-(--ink-100)/60">
        <div className="px-3 py-1">{children}</div>
      </ScrollArea>
    </section>
  );
}
