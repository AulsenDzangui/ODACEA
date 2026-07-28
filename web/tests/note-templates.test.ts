import { describe, expect, it } from "vitest";

import {
  REFONTE_LIBRE,
  appendNoteTemplate,
} from "@/lib/note-templates";

describe("appendNoteTemplate", () => {
  it("note vide → le gabarit seul, sans séparateur parasite", () => {
    expect(appendNoteTemplate("", REFONTE_LIBRE)).toBe(REFONTE_LIBRE);
  });

  it("note blanche (espaces/retours seuls) → le gabarit seul", () => {
    expect(appendNoteTemplate("  \n\t\n", REFONTE_LIBRE)).toBe(REFONTE_LIBRE);
  });

  it("note existante → conservée intégralement, gabarit ajouté après une ligne vide", () => {
    const note = "Fonds RH 2015–2022, attention aux dossiers personnels.";
    const result = appendNoteTemplate(note, REFONTE_LIBRE);
    expect(result).toBe(`${note}\n\n${REFONTE_LIBRE}`);
  });

  it("retours à la ligne finaux de la saisie normalisés (une seule ligne vide de séparation)", () => {
    const result = appendNoteTemplate("Ma note.\n\n\n", REFONTE_LIBRE);
    expect(result).toBe(`Ma note.\n\n${REFONTE_LIBRE}`);
  });

  it("le résultat contient le gabarit tel quel (contrat du garde anti-double-insertion)", () => {
    // Le bouton se désactive via `note.includes(gabarit)` : l'insertion doit
    // laisser le gabarit intact pour que le garde fonctionne.
    const result = appendNoteTemplate("Contexte.", REFONTE_LIBRE);
    expect(result.includes(REFONTE_LIBRE)).toBe(true);
  });
});

describe("REFONTE_LIBRE (opt-out du défaut conservateur d'AUD-001 ≥ 1.1.0)", () => {
  it("lève explicitement la conservation de l'ordre existant", () => {
    expect(REFONTE_LIBRE).toContain("ne conservez pas l'ordre existant");
  });

  it("référence la section « Écarts à l'ordre existant » du gabarit du prompt", () => {
    expect(REFONTE_LIBRE).toContain("Écarts à l'ordre existant");
  });
});
