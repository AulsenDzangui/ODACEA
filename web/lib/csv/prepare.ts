// La préparation du CSV (filtrage colonnes, nettoyage dates, échantillonnage,
// classement) est faite côté backend Python (`/parse`, `/audit`, `/classement/*`).

// Seuil de pré-activation : à l'import, le toggle d'échantillonnage est coché
// automatiquement si le CSV dépasse ce nombre d'Items (fichiers). Défaut
// intelligent — l'archiviste peut activer/désactiver à tout moment.
export const SAMPLE_ITEMS_THRESHOLD = 500;
