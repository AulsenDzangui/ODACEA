"use client";

import type { ClassementBatch, ResipStats, RevisionTurn } from "@/lib/csv/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { plS } from "@/lib/utils";
import { BarChart3, AlertTriangle, Layers, Sparkles } from "lucide-react";

/**
 * Onglet « Résultat » du classement — lecture seule, aucune action de
 * correction (celles-ci vivent dans `ClassementToolsPanel`, onglet « Outils »).
 * Regroupe ce qui était auparavant empilé en tête de la vue résultats :
 * bannières de contexte, rapport de couverture (5 tuiles) et alertes de
 * conformité au plan. Pure présentation — tous les compteurs sont
 * calculés côté `StepClassement` à partir de `csvFinal`.
 */
export function ClassementCoverageReport({
  classementRevisions,
  classementBatches,
  nNewRg,
  nNewItems,
  nOrigItems,
  missing,
  nNoDate,
  nExtFixed,
  stats,
  planEcarts,
  nAbsentLlm,
  nUnknownTarget,
}: {
  classementRevisions: RevisionTurn[];
  classementBatches: ClassementBatch[] | null;
  nNewRg: number;
  nNewItems: number;
  nOrigItems: number;
  missing: number;
  nNoDate: number;
  nExtFixed: number;
  stats: ResipStats | undefined;
  planEcarts: number;
  nAbsentLlm: number;
  nUnknownTarget: number;
}) {
  return (
    <div className="space-y-4 pt-3">
      {classementRevisions.length > 0 && (
        // Un classement révisé ne se relit pas comme un premier jet :
        // on dit lequel on regarde, et sur quelles consignes.
        <Alert>
          <Sparkles className="h-4 w-4" />
          <AlertTitle>
            Classement révisé — tour {classementRevisions.length}
          </AlertTitle>
          <AlertDescription>
            <ul className="space-y-0.5 text-xs">
              {classementRevisions.map((t, i) => (
                <li key={`${t.at}-${i}`}>• {t.consigne}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {classementBatches && (
        <Alert>
          <Layers className="h-4 w-4" />
          <AlertDescription>
            Classement produit en{" "}
            <strong>{classementBatches.length} lots</strong>, fusionnés et
            convertis en une seule passe, identifiants et dates cohérents
            sur l&apos;ensemble.
          </AlertDescription>
        </Alert>
      )}

      <h3 className="flex items-center gap-2 text-lg font-semibold text-(--ink-900)">
        <BarChart3 className="h-4 w-4" />
        Rapport de couverture
      </h3>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Metric label="Dossiers créés" value={nNewRg} />
        <Metric
          label="Items classés"
          value={`${nNewItems} / ${nOrigItems}`}
          delta={missing > 0 ? `-${missing} non classé${plS(missing)}` : undefined}
          deltaKind="bad"
        />
        <Metric
          label="Sans date"
          value={nNoDate}
          delta={nNoDate > 0 ? "À compléter" : undefined}
          deltaKind="bad"
        />
        <Metric
          label="Extensions corrigées"
          value={nExtFixed}
          delta={nExtFixed > 0 ? "Vérifier" : undefined}
          deltaKind="bad"
        />
        <Metric
          label="Respect du plan"
          value={
            !stats
              ? "—"
              : !stats.planParsed
                ? "—"
                : stats.planMatches
                  ? "Conforme"
                  : `${planEcarts} écart${plS(planEcarts)}`
          }
          delta={
            !stats
              ? "Relancer le classement"
              : !stats.planParsed
                ? "Arborescence du plan illisible"
                : stats.planMatches
                  ? "Identique au plan d'audit"
                  : `${stats.foldersOffPlan.length} hors plan · ${stats.foldersMissing.length} manquant${plS(stats.foldersMissing.length)}`
          }
          deltaKind={stats?.planMatches ? "good" : "bad"}
        />
      </div>

      {stats &&
        stats.planParsed &&
        (!stats.planMatches || stats.itemsMalformed > 0) && (
          <Alert variant="warning">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>L&apos;arborescence du classement diffère du plan d&apos;audit</AlertTitle>
            <AlertDescription className="space-y-1 text-sm">
              {stats.foldersOffPlan.length > 0 && (
                <p className="mb-0!">
                  <strong>Dossiers hors plan</strong> (inventés au classement) :{" "}
                  {stats.foldersOffPlan.join(", ")}
                </p>
              )}
              {stats.foldersMissing.length > 0 && (
                <p className="mb-0!">
                  <strong>Dossiers du plan non réalisés</strong> (aucun contenu) :{" "}
                  {stats.foldersMissing.join(", ")}
                </p>
              )}
              {stats.itemsMalformed > 0 && (
                <p className="mb-0!">
                  <strong>{stats.itemsMalformed} fichier{plS(stats.itemsMalformed)} à cible malformée</strong>{" "}
                  (le modèle a indiqué un nom de fichier au lieu d&apos;un
                  dossier) rattaché{plS(stats.itemsMalformed)} à la racine. Voir les avertissements de
                  conversion pour plus de détails.
                </p>
              )}
            </AlertDescription>
          </Alert>
        )}

      {missing > 0 && (nAbsentLlm > 0 || nUnknownTarget > 0) && (
        <p className="text-xs text-(--ink-500)">
          Détail des non classés :{" "}
          {[
            nAbsentLlm > 0
              ? `${nAbsentLlm} absent${plS(nAbsentLlm)} de la sortie LLM`
              : null,
            nUnknownTarget > 0
              ? `${nUnknownTarget} avec dossier cible inconnu`
              : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  delta,
  deltaKind,
}: {
  label: string;
  value: number | string;
  delta?: string;
  deltaKind?: "good" | "bad";
}) {
  return (
    <div className="rounded-md border border-(--ink-100) bg-(--paper-50) p-3">
      <div className="text-xs text-(--ink-500)">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-(--ink-900)">{value}</div>
      {delta && (
        <div
          className={
            "mt-0.5 text-xs " +
            (deltaKind === "bad" ? "text-(--danger-500)" : "text-(--success-500)")
          }
        >
          {delta}
        </div>
      )}
    </div>
  );
}
