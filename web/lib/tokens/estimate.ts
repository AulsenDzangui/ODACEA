// L'estimation de tokens est calculée côté backend (`/parse` → `tokenEstimate`).
// On ne garde ici que le type (forme du payload renvoyé) et le formateur d'affichage.

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
};

export function formatTokens(n: number): string {
  if (n < 1000) return n.toLocaleString("fr-FR");
  return (n / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " k";
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
