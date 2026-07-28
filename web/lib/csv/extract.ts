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
