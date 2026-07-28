import { describe, it, expect } from "vitest";
import {
  anomalyCounts,
  anomaliesFromWarnings,
  type Anomaly,
} from "@/lib/csv/anomalies";

// La **catégorisation** des avertissements de conversion vit désormais côté
// moteur (`backend/core/anomalies.py`, testée par `tests/test_anomalies.py`) :
// /classement/finalize renvoie `resip.anomalies` déjà typées. Le front ne garde
// que la présentation — c'est ce qui est testé ici.

const ANOMALIES: Anomaly[] = [
  { category: "nonClasse", item: "a.jpg", detail: "absent", isItem: true },
  { category: "cibleInconnue", item: "b.pdf", detail: "cible vide", isItem: true },
  { category: "extension", item: "c.docx", detail: "c.pdf → c.docx", isItem: true },
  { category: "extension", item: "d.xlsx", detail: "d.csv → d.xlsx", isItem: true },
  { category: "autre", item: "", detail: "format inconnu", isItem: false },
];

describe("anomalyCounts", () => {
  it("compte par catégorie dans l'ordre de sévérité d'ANOMALY_KINDS", () => {
    expect(anomalyCounts(ANOMALIES)).toEqual([
      { category: "nonClasse", count: 1 },
      { category: "cibleInconnue", count: 1 },
      { category: "extension", count: 2 },
      { category: "autre", count: 1 },
    ]);
  });

  it("renvoie une liste vide sans anomalie", () => {
    expect(anomalyCounts([])).toEqual([]);
  });
});

describe("anomaliesFromWarnings (repli rétro-compatible)", () => {
  it("enveloppe chaque avertissement brut en anomalie « autre », rien perdu", () => {
    const warnings = ["msg 1", "msg 2"];
    const out = anomaliesFromWarnings(warnings);
    expect(out).toEqual([
      { category: "autre", item: "", detail: "msg 1", isItem: false },
      { category: "autre", item: "", detail: "msg 2", isItem: false },
    ]);
  });
});
