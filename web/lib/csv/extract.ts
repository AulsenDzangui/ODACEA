// Nettoyage des marqueurs de structure pour l'affichage Markdown du rapport
// d'audit et du plan. L'extraction des sections (extractPlans) et du CSV LLM
// (extractCsvFromResponse) est désormais faite côté backend Python.
export function stripStructureMarkers(text: string): string {
  let out = text.replace(
    /<!--\s*PLAN_STRUCTURE_(?:START|END)\s*-->\n?/gi,
    "",
  );
  out = out.replace(/\s*\[\d[\d\s–\-]*car\.\]/g, "");
  return out;
}

// Mode « plan seul » : isole ce que le modèle a produit **en dehors** du plan,
// pour servir de contrôle de conformité dans l'onglet « Rapport d'audit ».
// Supprime le bloc PLAN_STRUCTURE (markers inclus) et l'éventuel en-tête
// « PARTIE 2 / PLAN DE CLASSEMENT ». Un résidu vide = le modèle a respecté la
// consigne (uniquement le plan) ; un résidu non vide = dérive à examiner.
export function stripPlanBlock(text: string): string {
  let out = text.replace(
    /<!--\s*PLAN_STRUCTURE_START\s*-->[\s\S]*?<!--\s*PLAN_STRUCTURE_END\s*-->/gi,
    "",
  );
  // En-têtes de plan (Markdown) : « ## PARTIE 2 — PLAN DE CLASSEMENT »,
  // « ## PLAN DE CLASSEMENT », « ### Plan retenu … ».
  out = out.replace(
    /^#{1,6}\s*(?:PARTIE\s*2\s*[—\-–:]\s*)?PLAN DE CLASSEMENT.*$/gim,
    "",
  );
  out = out.replace(/^#{1,6}\s*Plan retenu.*$/gim, "");
  return out.trim();
}
