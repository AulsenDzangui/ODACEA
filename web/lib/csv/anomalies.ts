// ── Triage des anomalies de conversion ───────────────────────────────────────
// Présentation pure. La **catégorisation** des avertissements de conversion vit
// désormais côté moteur (`backend/core/anomalies.py`) : /classement/finalize
// renvoie directement la liste typée `resip.anomalies` (contrainte « moteur
// unique » — plus de re-parsing par regex en TypeScript). Ce module ne garde
// que la présentation : libellés/sévérité par catégorie (`ANOMALY_KINDS`) et
// tabulation des compteurs (`anomalyCounts`).

export type AnomalyCategory =
  | "nonClasse"
  | "cibleInconnue"
  | "pathIntrouvable"
  | "cibleMalformee"
  | "horsPlan"
  | "nonRealise"
  | "sousDossierCree"
  | "extension"
  | "autre";

export type Anomaly = {
  category: AnomalyCategory;
  /** Élément concerné : chemin d'item, nom de dossier, ou "" (global). */
  item: string;
  /** Complément (cible fautive, renommage…). */
  detail: string;
  /** true quand `item` est un chemin de fichier source (lien vers l'item). */
  isItem: boolean;
};

export const ANOMALY_KINDS: Record<
  AnomalyCategory,
  { label: string; severity: "danger" | "warning" | "info" }
> = {
  nonClasse: { label: "Non classé", severity: "danger" },
  cibleInconnue: { label: "Cible inconnue", severity: "danger" },
  pathIntrouvable: { label: "Chemin introuvable", severity: "danger" },
  cibleMalformee: { label: "Cible malformée", severity: "warning" },
  horsPlan: { label: "Dossier hors plan", severity: "warning" },
  nonRealise: { label: "Dossier non réalisé", severity: "warning" },
  sousDossierCree: { label: "Sous-dossier créé", severity: "info" },
  extension: { label: "Extension corrigée", severity: "info" },
  autre: { label: "Autre", severity: "info" },
};

/** Repli de présentation pour un projet persisté **avant** que le moteur ne
 *  renvoie `resip.anomalies` (l'ancien `csvFinal` ne portait que `warnings`).
 *  Aucune catégorisation : chaque avertissement brut devient une anomalie
 *  « autre » — rien n'est perdu, le détail reste lisible (re-finaliser le
 *  classement pour obtenir le triage typé). */
export function anomaliesFromWarnings(warnings: string[]): Anomaly[] {
  return warnings.map((w) => ({
    category: "autre",
    item: "",
    detail: w,
    isItem: false,
  }));
}

/** Comptes par catégorie, dans l'ordre de sévérité d'ANOMALY_KINDS. */
export function anomalyCounts(
  anomalies: Anomaly[],
): { category: AnomalyCategory; count: number }[] {
  const counts = new Map<AnomalyCategory, number>();
  for (const a of anomalies)
    counts.set(a.category, (counts.get(a.category) ?? 0) + 1);
  return (Object.keys(ANOMALY_KINDS) as AnomalyCategory[])
    .filter((c) => counts.has(c))
    .map((category) => ({ category, count: counts.get(category)! }));
}
