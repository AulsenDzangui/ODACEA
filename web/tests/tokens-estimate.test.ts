import { describe, expect, it } from "vitest";
import { formatCostEur, formatSampleN, formatTokens } from "@/lib/tokens/estimate";

// Le coût € indicatif est calculé côté moteur (`core/pricing.py`) ; le front
// ne fait que présenter le montant. `formatCostEur` est le miroir TypeScript de
// `core.pricing.format_cost_eur` (mêmes cas, même rendu fr).
describe("formatCostEur (miroir de core.pricing.format_cost_eur)", () => {
  it("renvoie '' pour null/undefined (modèle local ou inconnu : rien à afficher)", () => {
    expect(formatCostEur(null)).toBe("");
    expect(formatCostEur(undefined)).toBe("");
  });

  it("renvoie '0,00 €' pour 0 ou négatif", () => {
    expect(formatCostEur(0)).toBe("0,00 €");
    expect(formatCostEur(-1)).toBe("0,00 €");
  });

  it("renvoie '< 0,01 €' sous le seuil d'affichage", () => {
    expect(formatCostEur(0.0001)).toBe("< 0,01 €");
    expect(formatCostEur(0.009)).toBe("< 0,01 €");
  });

  it("formate un montant lisible à deux décimales, virgule française", () => {
    expect(formatCostEur(0.01)).toBe("0,01 €");
    expect(formatCostEur(0.12)).toBe("0,12 €");
    expect(formatCostEur(1.3)).toBe("1,30 €");
    expect(formatCostEur(12.4)).toBe("12,40 €");
  });

  it("arrondit à deux décimales", () => {
    expect(formatCostEur(0.125)).toBe("0,13 €");
    expect(formatCostEur(1.234)).toBe("1,23 €");
  });
});

describe("formatTokens", () => {
  it("affiche les petits nombres tels quels (fr)", () => {
    expect(formatTokens(0)).toBe("0");
    expect(formatTokens(999)).toBe("999");
  });

  it("abrège en milliers au-delà de 1000", () => {
    expect(formatTokens(1000)).toBe("1 k");
    expect(formatTokens(3500)).toBe("3,5 k");
  });
});

// Le réglage d'échantillonnage recommandé est calculé côté moteur
// (`core/prep_budget.py`) ; le front ne fait qu'afficher le libellé. `formatSampleN`
// est le miroir TypeScript de `core.prep_budget._sample_label`.
describe("formatSampleN (miroir de core.prep_budget._sample_label)", () => {
  it("renvoie « tous » pour 0 ou négatif (aucun échantillonnage)", () => {
    expect(formatSampleN(0)).toBe("tous");
    expect(formatSampleN(-1)).toBe("tous");
  });

  it("renvoie « N/dossier » pour un échantillonnage actif", () => {
    expect(formatSampleN(3)).toBe("3/dossier");
    expect(formatSampleN(5)).toBe("5/dossier");
  });
});
