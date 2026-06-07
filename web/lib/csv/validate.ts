import { REQUIRED_COLUMNS, VALID_DESCRIPTION_LEVELS } from "./constants";
import type { SedaRow } from "./types";

export function validateCsv(rows: SedaRow[]): string[] {
  const errors: string[] = [];
  if (rows.length === 0) {
    errors.push("Le CSV est vide.");
    return errors;
  }

  const columns = new Set(Object.keys(rows[0]));
  const missing = REQUIRED_COLUMNS.filter((c) => !columns.has(c));
  if (missing.length > 0) {
    errors.push(`Colonnes manquantes : ${missing.join(", ")}`);
  }

  if (columns.has("Content.DescriptionLevel")) {
    const validSet = new Set<string>(VALID_DESCRIPTION_LEVELS);
    const invalid = rows.filter(
      (r) =>
        r["Content.DescriptionLevel"] &&
        !validSet.has(r["Content.DescriptionLevel"]),
    );
    if (invalid.length > 0) {
      errors.push(
        `${invalid.length} ligne(s) avec Content.DescriptionLevel invalide (valeurs acceptées : ${VALID_DESCRIPTION_LEVELS.join(", ")})`,
      );
    }
  }

  if (columns.has("ID")) {
    const seen = new Map<string, number>();
    for (const r of rows) {
      const id = r["ID"];
      if (!id) continue;
      seen.set(id, (seen.get(id) ?? 0) + 1);
    }
    const dups = Array.from(seen.values()).reduce(
      (n, count) => n + (count > 1 ? count : 0),
      0,
    );
    if (dups > 0) errors.push(`${dups} ID dupliqué(s) détecté(s)`);
  }

  return errors;
}

export function validateOutputCsv(rows: SedaRow[]): string[] {
  const errors = validateCsv(rows);
  if (rows.length === 0) return errors;
  const columns = new Set(Object.keys(rows[0]));
  if (columns.has("ID") && columns.has("ParentID")) {
    const allIds = new Set(rows.map((r) => r["ID"]).filter(Boolean));
    const orphans = rows.filter((r) => {
      const p = (r["ParentID"] ?? "").trim();
      return p !== "" && !allIds.has(p);
    });
    if (orphans.length > 0) {
      errors.push(
        `${orphans.length} Item(s) orphelin(s) — ParentID introuvable`,
      );
    }
    const roots = rows.filter((r) => !(r["ParentID"] ?? "").trim());
    if (roots.length === 0) {
      errors.push("Aucun élément racine (aucune ligne avec ParentID vide)");
    }
  }
  return errors;
}
