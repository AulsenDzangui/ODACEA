// Utilitaires génériques de découpage et seuil d'échantillonnage. La préparation
// du CSV (filtrage colonnes, nettoyage dates, échantillonnage, classement) est
// désormais faite côté backend Python (`/parse`, `/audit`, `/classement/*`).

// Seuil de pré-activation : à l'import, le toggle d'échantillonnage est coché
// automatiquement si le CSV dépasse ce nombre d'Items (fichiers). Défaut
// intelligent — l'archiviste peut activer/désactiver à tout moment.
export const SAMPLE_ITEMS_THRESHOLD = 500;

export function chunk<T>(arr: T[], size: number): T[][] {
  if (size <= 0) return [arr];
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    out.push(arr.slice(i, i + size));
  }
  return out;
}
