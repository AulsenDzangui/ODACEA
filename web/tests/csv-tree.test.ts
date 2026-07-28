import { describe, it, expect } from "vitest";
import { buildCsvTree, searchCsvTree } from "@/lib/csv/csv-tree";
import type { SedaRow } from "@/lib/csv/types";

const rows: SedaRow[] = [
  { ID: "1", ParentID: "", File: ".", "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Fonds" },
  { ID: "2", ParentID: "1", File: "cantine", "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Cantine" },
  { ID: "3", ParentID: "2", File: "cantine\\menu mars.pdf", "Content.DescriptionLevel": "Item", "Content.Title": "menu mars.pdf" },
  { ID: "4", ParentID: "1", File: "divers", "Content.DescriptionLevel": "RecordGrp", "Content.Title": "Divers" },
  { ID: "5", ParentID: "4", File: "divers\\note.docx", "Content.DescriptionLevel": "Item", "Content.Title": "note de service.docx" },
];

describe("searchCsvTree", () => {
  it("marque le fichier trouvé et tout son trajet (ancêtres)", () => {
    const tree = buildCsvTree(rows);
    const { matched, withMatch } = searchCsvTree(tree, "menu");
    expect([...matched]).toEqual(["3"]);
    // Trajet : racine (1) → cantine (2) → fichier (3).
    expect(withMatch).toEqual(new Set(["1", "2", "3"]));
    // La branche « divers » n'est pas sur le trajet.
    expect(withMatch.has("4")).toBe(false);
  });

  it("cherche aussi dans le chemin (colonne File), insensible à la casse", () => {
    const tree = buildCsvTree(rows);
    const { matched } = searchCsvTree(tree, "DIVERS\\NOTE");
    expect([...matched]).toEqual(["5"]);
  });

  it("requête vide : aucun marquage", () => {
    const tree = buildCsvTree(rows);
    const { matched, withMatch } = searchCsvTree(tree, "  ");
    expect(matched.size).toBe(0);
    expect(withMatch.size).toBe(0);
  });
});
