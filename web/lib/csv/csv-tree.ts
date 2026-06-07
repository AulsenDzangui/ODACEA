import type { SedaRow } from "./types";

export type CsvTreeNode = {
  id: string;
  parentId: string;
  file: string;
  title: string;
  isFolder: boolean;
  children: CsvTreeNode[];
  /** Nombre de descendants de type Item (fichiers). */
  itemCount: number;
};

export function buildCsvTree(rows: SedaRow[]): CsvTreeNode[] {
  const byId = new Map<string, CsvTreeNode>();

  for (const row of rows) {
    const id = row["ID"] ?? "";
    if (!id) continue;
    byId.set(id, {
      id,
      parentId: row["ParentID"] ?? "",
      file: row["File"] ?? "",
      title: row["Content.Title"] || row["File"] || id,
      isFolder: row["Content.DescriptionLevel"] === "RecordGrp",
      children: [],
      itemCount: 0,
    });
  }

  const roots: CsvTreeNode[] = [];
  for (const node of byId.values()) {
    if (node.parentId && byId.has(node.parentId)) {
      byId.get(node.parentId)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  function computeItemCount(node: CsvTreeNode): number {
    if (!node.isFolder) return 1;
    let count = 0;
    for (const child of node.children) count += computeItemCount(child);
    node.itemCount = count;
    return count;
  }
  for (const root of roots) computeItemCount(root);

  return roots;
}

export function csvTreeStats(rows: SedaRow[]): { folders: number; items: number } {
  let folders = 0;
  let items = 0;
  for (const row of rows) {
    if (row["Content.DescriptionLevel"] === "RecordGrp") folders++;
    else if (row["Content.DescriptionLevel"] === "Item") items++;
  }
  return { folders, items };
}
