"use client";

import { fr } from "./fr";

// ── Infrastructure i18n (D11) ────────────────────────────────────────────────
// Volontairement sans dépendance : un catalogue typé par locale + un accès
// `useT()`. Le français est la seule locale active aujourd'hui ; ajouter
// l'anglais = créer `en.ts` (satisfaisant le type `Messages`), l'enregistrer
// dans `catalogs`, et exposer un sélecteur de locale. La forme typée garantit
// qu'aucune clé n'est oubliée à la traduction et qu'aucun composant ne référence
// une clé inexistante.

export type Messages = typeof fr;
export type Locale = "fr";

const catalogs: Record<Locale, Messages> = { fr };

// Locale active. Constante pour l'instant (fr) ; point d'extension unique quand
// la sélection de langue arrivera (préférence persistée, en-tête Accept-Language…).
const ACTIVE_LOCALE: Locale = "fr";

/** Renvoie le catalogue de la locale active. Stable entre rendus. */
export function useT(): Messages {
  return catalogs[ACTIVE_LOCALE];
}

/** Accès hors composant (utilitaires). Même catalogue que useT(). */
export function getMessages(): Messages {
  return catalogs[ACTIVE_LOCALE];
}
