// Colonnes attendues d'un CSV Archifiltre/RESIP. Utilisé en présentation
// uniquement (détection d'un CSV final incomplet) — la validation d'entrée et
// de sortie est faite côté backend (`validate_csv` / `validate_output_csv`).
export const REQUIRED_COLUMNS = [
  "ID",
  "ParentID",
  "File",
  "Content.DescriptionLevel",
  "Content.Title",
  "Content.StartDate",
  "Content.EndDate",
] as const;
