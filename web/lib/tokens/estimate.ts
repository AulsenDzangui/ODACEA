// L'estimation de tokens est calculée côté backend (`/parse` → `tokenEstimate`).
// On ne garde ici que le type (forme du payload renvoyé) et le formateur d'affichage.

/** Coût d'entrée indicatif €, joint par `/parse` quand un modèle cloud
 *  connu est fourni. `null` pour un modèle local ou inconnu (rien à afficher).
 *  Forme renvoyée par `core.pricing.estimate_cost_eur` (l'estimation a priori ne
 *  connaît que l'entrée → `totalEur` == `inputEur`, `outputEur` == 0). */
export type CostEstimate = {
  /** Libellé tarifaire affichable (ex. « Claude Opus »). */
  label: string;
  /** Identifiant du modèle facturé. */
  model: string;
  /** Date de la grille tarifaire locale (`PRICE_TABLE_DATE`). */
  priceDate: string;
  inputEurPerM: number;
  outputEurPerM: number;
  inputEur: number;
  outputEur: number;
  totalEur: number;
};

/** Recommandation de budget d'entrée AUD-001 par taille de vrac, jointe par
 *  `/parse` au `tokenEstimate`. Calculée côté moteur (`core.prep_budget`) ; le
 *  front ne fait que la présenter. `currentSampleN`/`recommendedSampleN` valent
 *  `0` quand l'échantillonnage est désactivé (tous les fichiers envoyés). */
export type BudgetRecommendation = {
  /** Nombre d'Item (fichiers) du vrac — clé de choix du palier. */
  itemCount: number;
  /** Libellé du palier (« petit », « moyen », « grand », « très grand »). */
  tier: string;
  /** Échantillonnage actuel (`PrepOptions.effective_sample_n`). */
  currentSampleN: number;
  currentCleanDates: boolean;
  /** Échantillonnage recommandé pour ce vrac. */
  recommendedSampleN: number;
  recommendedCleanDates: boolean;
  /** Vrai quand le réglage courant correspond déjà à la recommandation. */
  matchesRecommendation: boolean;
  /** Tokens d'entrée AUD-001 estimés au réglage recommandé (à comparer à `auditTokens`). */
  estimatedAuditTokensAtRecommended: number;
  /** Justification du palier (table locale). */
  rationale: string;
  /** Date de la table de paliers (`BUDGET_TIERS_DATE`). */
  tableDate: string;
};

export type TokenEstimate = {
  /** Tokens en entrée pour AUD-001 (prompt système + message utilisateur avec CSV). */
  auditTokens: number;
  /** Tokens en entrée pour un lot CLA-001 (sans le plan d'audit, non connu à cette étape). */
  classementTokensPerBatch: number;
  /** Nombre de lots pour CLA-001. */
  classementBatches: number;
  /** Total tokens CLA-001 pour tous les lots (sans plan d'audit). */
  classementTotalTokens: number;
  /** Somme AUD-001 + CLA-001 (sans plan d'audit). */
  totalTokens: number;
  /** Coût d'entrée indicatif € — présent seulement si `model` cloud connu
   *  fourni à `/parse` ; `null` pour un modèle local/inconnu. */
  costEstimate?: CostEstimate | null;
  /** Recommandation de budget d'entrée AUD-001 — indépendante du modèle. */
  budgetRecommendation?: BudgetRecommendation | null;
};

export function formatTokens(n: number): string {
  if (n < 1000) return n.toLocaleString("fr-FR");
  return (n / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " k";
}

/** Formate un montant € lisible. Miroir de `core.pricing.format_cost_eur` :
 *  `null` → '' (rien à afficher, modèle local/inconnu) · ≤ 0 → '0,00 €' ·
 *  < 0,01 → '< 0,01 €' · sinon '12,40 €' (2 décimales, virgule). */
export function formatCostEur(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return "";
  if (amount <= 0) return "0,00 €";
  if (amount < 0.01) return "< 0,01 €";
  return amount.toFixed(2).replace(".", ",") + " €";
}

/** Libellé d'un réglage d'échantillonnage d'entrée AUD-001. Miroir de
 *  `core.prep_budget._sample_label` : `0` → « tous » (aucun échantillonnage),
 *  sinon « N/dossier ». */
export function formatSampleN(n: number): string {
  return n <= 0 ? "tous" : `${n}/dossier`;
}

/** Formate une durée (en millisecondes) en texte lisible français.
 *  Miroir de `backend/core/tokens.py::format_duration` :
 *  < 60 s → '12,4 s' · < 1 h → '3 min 05 s' · ≥ 1 h → '1 h 02 min'. */
export function formatDuration(ms: number): string {
  const seconds = Number.isFinite(ms) && ms > 0 ? ms / 1000 : 0;
  if (seconds < 60) {
    return seconds.toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " s";
  }
  if (seconds < 3600) {
    const total = Math.round(seconds);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m} min ${String(s).padStart(2, "0")} s`;
  }
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  return `${h} h ${String(m).padStart(2, "0")} min`;
}
