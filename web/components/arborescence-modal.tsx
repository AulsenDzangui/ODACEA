"use client";

import { useMemo } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { buildCsvTree, csvTreeStats } from "@/lib/csv/csv-tree";
import { CsvTreeView } from "@/components/csv-tree-view";
import type { SedaRow, ResipResult } from "@/lib/csv/types";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  csvOriginal: SedaRow[];
  csvFinal: ResipResult;
};

export function ArborescenceModal({
  open,
  onOpenChange,
  csvOriginal,
  csvFinal,
}: Props) {
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-3xl">
        <DialogHeader className="px-4 pt-4 pb-3">
          <DialogTitle>Vérification de l&apos;arborescence</DialogTitle>
        </DialogHeader>
        <Tabs defaultValue="final">
          <div className="px-4 pb-2">
            <TabsList className="w-full">
              <TabsTrigger value="original" className="flex-1 gap-2">
                <span>Avant classement</span>
                <span className="text-xs font-normal opacity-60">
                  {statsOriginal.folders} dossiers · {statsOriginal.items}{" "}
                  fichiers
                </span>
              </TabsTrigger>
              <TabsTrigger value="final" className="flex-1 gap-2">
                <span>Après classement</span>
                <span className="text-xs font-normal opacity-60">
                  {statsFinal.folders} dossiers · {statsFinal.items} fichiers
                </span>
              </TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="original" className="m-0">
            <ScrollArea className="h-[62vh]">
              <div className="px-3 py-1">
                <CsvTreeView nodes={treeOriginal} />
              </div>
            </ScrollArea>
          </TabsContent>
          <TabsContent value="final" className="m-0">
            <ScrollArea className="h-[62vh]">
              <div className="px-3 py-1">
                <CsvTreeView nodes={treeFinal} />
              </div>
            </ScrollArea>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
