// Statistiques de projets (fonds) — agrégation **locale** des projets traités.
//
// Contrainte « moteur unique » : aucune logique métier n'est (ré)implémentée
// ici. La conformité au plan (`planMatches`, `foldersOffPlan`…) est calculée par
// le backend Python (`convert_classement_to_resip`) et persistée telle quelle
// dans chaque projet (`csvFinal.stats`). Ce module ne fait que **tabuler** des
// mesures déjà produites par le moteur — c'est de la présentation, comme l'exige
// Tableau de bord local (« … purement localStorage/fichiers, pas de serveur »).

import type { SedaRow } from "@/lib/csv/types";
import type { ProjectSnapshot } from "@/lib/persistence";
import type { WizardStep } from "@/lib/store";

/** Mesures compactes d'un projet, dérivées de son instantané persisté. Stockées
 *  dans l'index des projets (au moment de l'enregistrement) pour que le tableau
 *  de bord se construise sans recharger les gros CSV. Toutes les valeurs issues
 *  du LLM/moteur sont `null` tant que l'étape correspondante n'a pas tourné. */
export type ProjectMetrics = {
  /** Volume : nombre d'Item (fichiers) dans le CSV d'origine. */
  itemCount: number | null;
  /** Nombre d'Item dans le CSV RESIP final (fichiers effectivement classés). */
  classifiedCount: number | null;
  /** Conformité : l'arborescence du plan a pu être lue (mesure possible). */
  planParsed: boolean | null;
  /** Conformité : plan lu ET aucun écart dans les deux sens. */
  planMatches: boolean | null;
  /** Dossiers créés hors du plan validé. */
  foldersOffPlan: number | null;
  /** Dossiers du plan restés sans contenu. */
  foldersMissing: number | null;
  /** Items à cible malformée (rattachés à la racine). */
  itemsMalformed: number | null;
  /** Durée totale du traitement (audit + classement), en millisecondes. */
  durationTotalMs: number | null;
  /** Tokens totaux consommés (audit + classement). */
  totalTokens: number | null;
  /** Étape atteinte par le projet. */
  step: WizardStep;
  /** Le projet a produit un CSV RESIP final (traitement mené à son terme). */
  completed: boolean;
};

function countItems(rows: SedaRow[] | null | undefined): number | null {
  if (!rows) return null;
  return rows.filter((r) => r["Content.DescriptionLevel"] === "Item").length;
}

/** Somme de deux mesures optionnelles : `null` seulement si les deux le sont
 *  (un agent non encore exécuté ne compte pas comme un zéro mesuré). */
function sumOptional(a: number | null, b: number | null): number | null {
  if (a === null && b === null) return null;
  return (a ?? 0) + (b ?? 0);
}

/** Dérive les mesures compactes d'un instantané de projet. Pur, sans I/O. */
export function computeProjectMetrics(snapshot: ProjectSnapshot): ProjectMetrics {
  const final = snapshot.csvFinal;
  const stats = final?.stats ?? null;
  return {
    itemCount: countItems(snapshot.csvOriginal),
    classifiedCount: final ? countItems(final.rows) : null,
    planParsed: stats ? stats.planParsed : null,
    planMatches: stats ? stats.planMatches : null,
    foldersOffPlan: stats ? stats.foldersOffPlan.length : null,
    foldersMissing: stats ? stats.foldersMissing.length : null,
    itemsMalformed: stats ? stats.itemsMalformed : null,
    durationTotalMs: sumOptional(
      snapshot.durationAudit ?? null,
      snapshot.durationClassementTotal ?? null,
    ),
    totalTokens: sumOptional(
      snapshot.usageAudit?.totalTokens ?? null,
      snapshot.usageClassementTotal?.totalTokens ?? null,
    ),
    step: snapshot.step,
    completed: final !== null && final !== undefined,
  };
}

/** Synthèse agrégée sur l'ensemble des fonds traités. */
export type FondsAggregate = {
  projectCount: number;
  /** Projets ayant produit un CSV final. */
  completedCount: number;
  /** Volume cumulé (Item du CSV d'origine). */
  totalItems: number;
  /** Fichiers classés cumulés (Item du CSV final). */
  totalClassified: number;
  totalDurationMs: number;
  totalTokens: number;
  /** Projets dont la conformité a pu être mesurée (plan lu). */
  conformityMeasured: number;
  /** Parmi les mesurés, ceux où le classement épouse exactement le plan. */
  conformityMatching: number;
  /** `conformityMatching / conformityMeasured`, ou `null` si rien de mesuré. */
  conformityRate: number | null;
  totalFoldersOffPlan: number;
  totalItemsMalformed: number;
};

/** Agrège une liste de mesures de projets en une synthèse de fonds. Pur. */
export function aggregateFonds(metrics: ProjectMetrics[]): FondsAggregate {
  const agg: FondsAggregate = {
    projectCount: metrics.length,
    completedCount: 0,
    totalItems: 0,
    totalClassified: 0,
    totalDurationMs: 0,
    totalTokens: 0,
    conformityMeasured: 0,
    conformityMatching: 0,
    conformityRate: null,
    totalFoldersOffPlan: 0,
    totalItemsMalformed: 0,
  };
  for (const m of metrics) {
    if (m.completed) agg.completedCount += 1;
    agg.totalItems += m.itemCount ?? 0;
    agg.totalClassified += m.classifiedCount ?? 0;
    agg.totalDurationMs += m.durationTotalMs ?? 0;
    agg.totalTokens += m.totalTokens ?? 0;
    agg.totalFoldersOffPlan += m.foldersOffPlan ?? 0;
    agg.totalItemsMalformed += m.itemsMalformed ?? 0;
    if (m.planParsed === true) {
      agg.conformityMeasured += 1;
      if (m.planMatches === true) agg.conformityMatching += 1;
    }
  }
  agg.conformityRate =
    agg.conformityMeasured > 0
      ? agg.conformityMatching / agg.conformityMeasured
      : null;
  return agg;
}
