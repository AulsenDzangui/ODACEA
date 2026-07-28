"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useT } from "@/lib/i18n";
import {
  listProjectMetrics,
  type ProjectMetricsEntry,
} from "@/lib/persistence";
import { aggregateFonds, type ProjectMetrics } from "@/lib/fonds-stats";
import { formatTokens, formatDuration } from "@/lib/tokens/estimate";

// Tableau de bord local des fonds traités. Page client : toutes les
// données viennent de `localStorage` (aucun appel réseau, aucun serveur). La
// conformité affichée est calculée par le moteur Python et persistée telle
// quelle — ici on ne fait qu'agréger et présenter (contrainte moteur unique).

function StatusLabel({ metrics }: { metrics: ProjectMetrics | null }) {
  const t = useT().dashboard;
  if (!metrics) return <>{t.notApplicable}</>;
  if (metrics.completed) return <>{t.statusClassement}</>;
  if (metrics.step === "audit") return <>{t.statusAudit}</>;
  if (metrics.step === "classement") return <>{t.statusClassement}</>;
  return <>{t.statusUpload}</>;
}

function ConformityCell({ metrics }: { metrics: ProjectMetrics | null }) {
  const t = useT().dashboard;
  if (!metrics || metrics.planParsed !== true) {
    return (
      <Badge variant="ghost" className="text-muted-foreground">
        {t.conformityUnmeasured}
      </Badge>
    );
  }
  if (metrics.planMatches) {
    return <Badge variant="secondary">{t.conformityMatch}</Badge>;
  }
  return (
    <Badge variant="destructive">
      {t.conformityOffPlan(metrics.foldersOffPlan ?? 0)}
    </Badge>
  );
}

function SummaryCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl tabular-nums">{value}</CardTitle>
      </CardHeader>
      {hint ? (
        <CardContent className="pt-0 text-xs text-muted-foreground">
          {hint}
        </CardContent>
      ) : null}
    </Card>
  );
}

export default function TableauDeBordPage() {
  const t = useT().dashboard;
  // Lecture localStorage : seulement après le mount (absent côté serveur).
  const [entries, setEntries] = useState<ProjectMetricsEntry[] | null>(null);

  useEffect(() => {
    // localStorage absent côté serveur : on lit après le mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEntries(listProjectMetrics());
  }, []);

  const agg =
    entries && entries.length > 0
      ? aggregateFonds(
          entries
            .map((e) => e.metrics)
            .filter((m): m is ProjectMetrics => m !== null),
        )
      : null;

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader />

      <main className="flex-1 px-6 pt-8 pb-10">
        <div className="mx-auto max-w-6xl">
          <div className="mb-6 flex items-start justify-between gap-4">
            <div>
              <h1 className="font-heading text-2xl font-semibold text-(--ink-900)">
                {t.title}
              </h1>
              <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
                {t.subtitle}
              </p>
            </div>
            <Button asChild variant="ghost" size="default">
              <Link href="/">
                <ArrowLeft className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">{t.backToApp}</span>
              </Link>
            </Button>
          </div>

          {entries === null ? null : entries.length === 0 ? (
            <p className="rounded-md border border-dashed border-(--ink-200) p-8 text-center text-sm text-muted-foreground">
              {t.empty}
            </p>
          ) : (
            <>
              {agg ? (
                <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  <SummaryCard
                    label={t.cardProjects}
                    value={agg.projectCount.toLocaleString("fr-FR")}
                    hint={t.cardProjectsHint(agg.completedCount)}
                  />
                  <SummaryCard
                    label={t.cardVolume}
                    value={agg.totalItems.toLocaleString("fr-FR")}
                    hint={t.cardVolumeHint(agg.totalClassified)}
                  />
                  <SummaryCard
                    label={t.cardConformity}
                    value={
                      agg.conformityRate === null
                        ? t.notApplicable
                        : `${Math.round(agg.conformityRate * 100)} %`
                    }
                    hint={t.cardConformityHint(agg.conformityMeasured)}
                  />
                  <SummaryCard
                    label={t.cardDuration}
                    value={
                      agg.totalDurationMs > 0
                        ? formatDuration(agg.totalDurationMs)
                        : t.notApplicable
                    }
                  />
                  <SummaryCard
                    label={t.cardTokens}
                    value={
                      agg.totalTokens > 0
                        ? formatTokens(agg.totalTokens)
                        : t.notApplicable
                    }
                  />
                  <SummaryCard
                    label={t.cardAnomalies}
                    value={agg.totalFoldersOffPlan.toLocaleString("fr-FR")}
                    hint={t.cardAnomaliesHint(agg.totalItemsMalformed)}
                  />
                </div>
              ) : null}

              <div className="overflow-x-auto rounded-md border border-(--ink-100)">
                <table className="w-full border-collapse text-sm">
                  <caption className="sr-only">{t.tableCaption}</caption>
                  <thead>
                    <tr className="border-b border-(--ink-100) bg-(--paper-100) text-left text-xs text-muted-foreground">
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t.colProject}
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t.colDate}
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t.colStatus}
                      </th>
                      <th
                        scope="col"
                        className="px-3 py-2 text-right font-medium tabular-nums"
                      >
                        {t.colVolume}
                      </th>
                      <th
                        scope="col"
                        className="px-3 py-2 text-right font-medium tabular-nums"
                      >
                        {t.colClassified}
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        {t.colConformity}
                      </th>
                      <th
                        scope="col"
                        className="px-3 py-2 text-right font-medium tabular-nums"
                      >
                        {t.colDuration}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map(({ entry, metrics }) => (
                      <tr
                        key={entry.stem}
                        className="border-b border-(--ink-100) last:border-0"
                      >
                        <th
                          scope="row"
                          className="px-3 py-2 text-left font-medium text-(--ink-900)"
                        >
                          <Link
                            href={`/?p=${encodeURIComponent(entry.stem)}`}
                            className="hover:underline"
                          >
                            {entry.name}
                          </Link>
                        </th>
                        <td className="px-3 py-2 text-muted-foreground">
                          {new Date(entry.savedAt).toLocaleDateString("fr-FR")}
                        </td>
                        <td className="px-3 py-2">
                          <StatusLabel metrics={metrics} />
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {metrics?.itemCount ?? t.notApplicable}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {metrics?.classifiedCount ?? t.notApplicable}
                        </td>
                        <td className="px-3 py-2">
                          <ConformityCell metrics={metrics} />
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {metrics?.durationTotalMs
                            ? formatDuration(metrics.durationTotalMs)
                            : t.notApplicable}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}
