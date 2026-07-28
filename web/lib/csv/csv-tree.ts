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

/** Résultat de recherche dans un arbre : nœuds correspondants et nœuds
 *  dont le sous-arbre contient au moins une correspondance (= trajet à
 *  surligner : la chaîne d'ancêtres d'un fichier trouvé). */
export type CsvTreeMatch = {
  matched: Set<string>;
  withMatch: Set<string>;
};

export function searchCsvTree(nodes: CsvTreeNode[], query: string): CsvTreeMatch {
  const matched = new Set<string>();
  const withMatch = new Set<string>();
  const q = query.trim().toLowerCase();
  if (!q) return { matched, withMatch };

  const visit = (node: CsvTreeNode): boolean => {
    const isMatch =
      node.title.toLowerCase().includes(q) ||
      node.file.toLowerCase().includes(q);
    if (isMatch) matched.add(node.id);
    let subtree = isMatch;
    for (const child of node.children) {
      if (visit(child)) subtree = true;
    }
    if (subtree) withMatch.add(node.id);
    return subtree;
  };
  for (const node of nodes) visit(node);
  return { matched, withMatch };
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
