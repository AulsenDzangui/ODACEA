import type { SedaRow } from "./types";

// Sérialisation CSV pour les téléchargements (export du CSV RESIP final et des
// CSV bruts LLM). Format aligné sur la sortie Python : séparateur `;`, toutes
// les cellules entre guillemets (QUOTE_ALL). Le parsing/validation du CSV
// d'entrée est fait côté backend (`/parse`).
export function stringifyCsv(rows: SedaRow[], columns?: string[]): string {
  const cols = columns ?? Object.keys(rows[0] ?? {});
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const head = cols.map(esc).join(";");
  const body = rows.map((r) => cols.map((c) => esc(r[c])).join(";")).join("\n");
  return rows.length > 0 ? `${head}\n${body}` : head;
}
