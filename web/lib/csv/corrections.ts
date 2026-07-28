// Apprentissage des corrections (opt-in) — utilitaire de **transport** pur.
//
// Le moteur Python est seul responsable du few-shot : sélection bornée des
// exemples, diversité des dossiers cibles, formulation du bloc injecté dans
// CLA-001 (`backend/core/corrections.py`). Le front ne fait que **collecter** les
// corrections validées par l'archiviste et les **renvoyer** au moteur via le
// corps `corrections` de /classement/batch — aucune logique métier (contrainte).
//
// `mergeCorrections` est la seule opération front : dédoublonner par chemin source
// en gardant la **dernière** valeur (l'archiviste a pu corriger un même fichier en
// plusieurs passes), dans un ordre stable. Pas de tri, pas de sélection : ces
// décisions appartiennent au moteur.
import type { CorrectionExample } from "@/lib/csv/types";

/**
 * Fusionne deux jeux de corrections par `path` : un `path` présent dans
 * `incoming` **remplace** son éventuelle valeur antérieure (la dernière
 * correction de l'archiviste fait foi), les autres sont conservées. L'ordre suit
 * la première apparition de chaque chemin (déterministe, lisible).
 */
export function mergeCorrections(
  existing: readonly CorrectionExample[],
  incoming: readonly CorrectionExample[],
): CorrectionExample[] {
  const byPath = new Map<string, CorrectionExample>();
  for (const c of existing) byPath.set(c.path, c);
  for (const c of incoming) byPath.set(c.path, c);
  return [...byPath.values()];
}
