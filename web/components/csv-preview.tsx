"use client";

import type { SedaRow } from "@/lib/csv/types";

type Props = {
  rows: SedaRow[];
  maxRows?: number;
};

export function CsvPreview({ rows, maxRows = 20 }: Props) {
  if (rows.length === 0) return null;
  const columns = Object.keys(rows[0]);
  const shown = rows.slice(0, maxRows);

  return (
    <div className="overflow-auto rounded-md border border-(--ink-100)">
      <table className="w-full text-xs">
        <thead className="bg-(--paper-100)">
          <tr>
            {columns.map((c) => (
              <th
                key={c}
                className="border-b border-(--ink-100) px-3 py-2 text-left font-semibold text-(--ink-700)"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((row, i) => (
            <tr
              key={i}
              className="border-b border-(--ink-100) odd:bg-(--paper-75) last:border-b-0 hover:bg-(--paper-100)"
            >
              {columns.map((c) => (
                <td
                  key={c}
                  className="max-w-[300px] truncate px-3 py-1.5 text-(--ink-700)"
                  title={row[c]}
                >
                  {row[c]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {rows.length > maxRows && (
          <tfoot>
            <tr>
              <td
                colSpan={columns.length}
                className="bg-(--paper-100) px-3 py-2 text-xs text-(--ink-500)"
              >
                {rows.length - maxRows} ligne(s) supplémentaire(s) non affichée(s).
              </td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}
