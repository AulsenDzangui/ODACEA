// Tests unitaires. `mergeCorrections`, seule opération front de
// l'apprentissage des corrections (transport pur ; le few-shot vit dans le moteur).
import { describe, expect, it } from "vitest";

import { mergeCorrections } from "@/lib/csv/corrections";
import type { CorrectionExample } from "@/lib/csv/types";

const c = (
  path: string,
  targetFolder: string,
  newTitle = "",
): CorrectionExample => ({ path, targetFolder, newTitle });

describe("mergeCorrections", () => {
  it("concatène deux jeux sans chemin commun, dans l'ordre d'apparition", () => {
    const out = mergeCorrections(
      [c("a/x.pdf", "1_Inscriptions")],
      [c("b/y.docx", "2_Cantine")],
    );
    expect(out).toEqual([
      c("a/x.pdf", "1_Inscriptions"),
      c("b/y.docx", "2_Cantine"),
    ]);
  });

  it("garde la dernière valeur pour un même chemin (re-correction)", () => {
    const out = mergeCorrections(
      [c("a/x.pdf", "1_Inscriptions", "v1")],
      [c("a/x.pdf", "3_Vie_scolaire", "v2")],
    );
    expect(out).toEqual([c("a/x.pdf", "3_Vie_scolaire", "v2")]);
  });

  it("conserve la position de première apparition lors d'une mise à jour", () => {
    const out = mergeCorrections(
      [c("a.pdf", "1_A"), c("b.pdf", "2_B")],
      [c("a.pdf", "9_Z")],
    );
    // a.pdf reste en tête, valeur mise à jour ; b.pdf inchangé après.
    expect(out.map((x) => x.path)).toEqual(["a.pdf", "b.pdf"]);
    expect(out[0].targetFolder).toBe("9_Z");
  });

  it("est neutre quand un côté est vide", () => {
    const base = [c("a.pdf", "1_A")];
    expect(mergeCorrections(base, [])).toEqual(base);
    expect(mergeCorrections([], base)).toEqual(base);
    expect(mergeCorrections([], [])).toEqual([]);
  });

  it("ne mute pas les tableaux d'entrée", () => {
    const existing = [c("a.pdf", "1_A")];
    const incoming = [c("b.pdf", "2_B")];
    mergeCorrections(existing, incoming);
    expect(existing).toHaveLength(1);
    expect(incoming).toHaveLength(1);
  });
});
