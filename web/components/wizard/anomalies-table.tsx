"use client";

import { useMemo, useState } from "react";
import {
  anomalyCounts,
  ANOMALY_KINDS,
  type Anomaly,
  type AnomalyCategory,
} from "@/lib/csv/anomalies";
import { Button } from "@/components/ui/button";
import { Pencil } from "lucide-react";

// ── Tableau de triage des anomalies ──────────────────────────────────────────
// Remplace la liste à plat des avertissements de conversion : anomalies
// groupées par type (filtres à compteurs), chaque ligne reliée à l'item
// concerné — « Corriger » ouvre le panneau de re-classement filtré sur
// le fichier. Les anomalies sont **catégorisées côté moteur** et reçues
// déjà typées (`resip.anomalies`) — ce composant ne fait que les présenter.

type Props = {
  anomalies: Anomaly[];
  /** Ouvre le panneau de correction filtré sur ce chemin. */
  onLocate?: (path: string) => void;
};

const SEVERITY_STYLES: Record<string, string> = {
  danger: "bg-(--danger-500)/10 text-(--danger-500)",
  warning: "bg-(--warning-500)/15 text-(--ink-700)",
  info: "bg-(--ink-100) text-(--ink-600)",
};

export function AnomaliesTable({ anomalies, onLocate }: Props) {
  const counts = useMemo(() => anomalyCounts(anomalies), [anomalies]);
  // null = toutes les catégories.
  const [filter, setFilter] = useState<AnomalyCategory | null>(null);

  const visible = filter
    ? anomalies.filter((a) => a.category === filter)
    : anomalies;

  return (
    <div className="space-y-2">
      {/* Filtres par catégorie, avec compteurs. */}
      <div
        className="flex flex-wrap items-center gap-1.5"
        role="group"
        aria-label="Filtrer les anomalies par type"
      >
        <FilterChip
          active={filter === null}
          label={`Toutes (${anomalies.length})`}
          onClick={() => setFilter(null)}
        />
        {counts.map(({ category, count }) => (
          <FilterChip
            key={category}
            active={filter === category}
            label={`${ANOMALY_KINDS[category].label} (${count})`}
            onClick={() =>
              setFilter((f) => (f === category ? null : category))
            }
          />
        ))}
      </div>

      <div className="overflow-x-auto rounded-md border border-(--ink-100)">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-(--ink-100) bg-(--paper-100) text-left text-(--ink-500)">
              <th scope="col" className="w-36 px-2 py-1.5 font-medium">
                Type
              </th>
              <th scope="col" className="px-2 py-1.5 font-medium">
                Élément
              </th>
              <th scope="col" className="px-2 py-1.5 font-medium">
                Détail
              </th>
              {onLocate && (
                <th scope="col" className="w-24 px-2 py-1.5 font-medium">
                  <span className="sr-only">Action</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {visible.map((a, i) => {
              const kind = ANOMALY_KINDS[a.category];
              return (
                <tr
                  key={i}
                  className="border-b border-(--ink-100)/60 last:border-0"
                >
                  <td className="px-2 py-1">
                    <span
                      className={
                        "inline-block rounded px-1.5 py-0.5 text-[10px] font-medium " +
                        SEVERITY_STYLES[kind.severity]
                      }
                    >
                      {kind.label}
                    </span>
                  </td>
                  <td
                    className="max-w-72 truncate px-2 py-1 font-mono text-(--ink-700)"
                    title={a.item || undefined}
                  >
                    {a.item}
                  </td>
                  <td className="max-w-80 truncate px-2 py-1 text-(--ink-600)" title={a.detail}>
                    {a.detail}
                  </td>
                  {onLocate && (
                    <td className="px-2 py-1 text-right">
                      {a.isItem && a.item && (
                        <Button
                          variant="ghost"
                          size="xs"
                          onClick={() => onLocate(a.item)}
                          aria-label={`Corriger ${a.item}`}
                        >
                          <Pencil className="mr-1 h-3 w-3" />
                          Corriger
                        </Button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
            {visible.length === 0 && (
              <tr>
                <td
                  colSpan={onLocate ? 4 : 3}
                  className="px-2 py-3 text-center text-(--ink-500)"
                >
                  Aucune anomalie dans cette catégorie.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FilterChip({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={
        "rounded-full border px-2.5 py-0.5 text-xs transition-colors " +
        (active
          ? "border-(--graphite-700) bg-(--graphite-700) text-white"
          : "border-(--ink-200) bg-transparent text-(--ink-600) hover:bg-(--paper-100)")
      }
    >
      {label}
    </button>
  );
}
