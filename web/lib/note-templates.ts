// Gabarits d'annotation insérables dans la « Note contextuelle de l'archiviste »
// (canal `observation` d'AUD-001, transmis tel quel au backend). Texte destiné au
// MODÈLE : il reste en français comme les prompts (hors périmètre i18n, cf.
// lib/i18n/fr.ts) — seuls les libellés des boutons d'insertion vivent dans le
// catalogue. Le gabarit est ajouté dans le textarea, donc visible et ajustable
// par l'archiviste avant l'audit ; il n'est jamais injecté à son insu côté
// système.

/**
 * Refonte libre (opt-out) : depuis AUD-001 1.1.0, le prompt conserve PAR DÉFAUT
 * l'ordre existant du fonds (respect de l'ordre originel — verdict STRUCTURÉ /
 * PARTIELLEMENT STRUCTURÉ / ABSENT, écarts limités à une liste fermée de
 * défauts). L'ancien gabarit RESPECT_PLAN_ORIGINE (opt-in, wording validé le
 * 2026-07-05 sur un fonds réel de 2 600 fichiers) est donc retiré : son principe
 * vit dans le prompt. Ce gabarit-ci inverse le défaut pour un vrac que
 * l'archiviste sait irrécupérable — le prompt fait primer la note contextuelle
 * sur ses règles internes. Les seuils du prompt (profondeur 4, seuils 10/20)
 * restent ajustables en écrivant la valeur voulue dans la note.
 */
export const REFONTE_LIBRE =
  "Refonte libre demandée : ne conservez pas l'ordre existant du fonds. " +
  "Concevez librement le plan de classement le mieux adapté aux documents " +
  "(fonctionnel, thématique, chronologique ou mixte), sans obligation de " +
  "conserver les dossiers existants. Dans « Écarts à l'ordre existant », " +
  "indiquez : « Refonte libre demandée par l'archiviste. »";

/**
 * Ajoute un gabarit à la suite d'une note existante, séparé par une ligne vide,
 * sans jamais écraser la saisie. Note vide ou blanche → le gabarit seul.
 */
export function appendNoteTemplate(current: string, template: string): string {
  const base = current.trimEnd();
  return base ? `${base}\n\n${template}` : template;
}
