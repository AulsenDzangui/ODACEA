"use client";

import { useWizard } from "@/lib/store";
import { StreamingMarkdown } from "@/components/streaming-markdown";
import { stripStructureMarkers } from "@/lib/csv/extract";
import { parsePlanModel, type PlanNode } from "@/lib/csv/plan-edit";

// ── Rapport imprimable (D6) ──────────────────────────────────────────────────
// Document destiné à l'impression / export PDF (via window.print, déclenché par
// le bouton « Exporter en PDF »). Masqué à l'écran, révélé par la règle
// @media print de globals.css. Réunit, pour la traçabilité institutionnelle :
// le rapport d'audit, le plan de classement (arbre lisible) et les statistiques
// de conformité du classement. Tout est lu depuis le store — aucune donnée ne
// quitte le poste.

export function PrintReport() {
  const {
    rapportAudit,
    briefMode,
    planValide,
    planNotes,
    csvFinal,
    csvFilename,
    currentName,
    promptVersionAudit,
    promptVersionClassement,
    modelAudit,
    modelClassement,
  } = useWizard();

  // Rien à imprimer tant qu'aucun audit n'a produit de plan/rapport.
  if (!rapportAudit && !planValide) return null;

  const planModel = parsePlanModel(planValide);
  const stats = csvFinal?.stats;
  const today = new Date().toLocaleDateString("fr-FR", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  const nItems = csvFinal
    ? csvFinal.rows.filter((r) => r["Content.DescriptionLevel"] === "Item").length
    : 0;
  const nFolders = csvFinal
    ? csvFinal.rows.filter((r) => r["Content.DescriptionLevel"] === "RecordGrp")
        .length
    : 0;

  return (
    <div
      id="odacea-print-root"
      aria-hidden
      className="hidden bg-white px-1 text-sm text-black print:block"
    >
      <header className="odacea-print-avoid-break mb-6 border-b border-black/30 pb-3">
        <h1 className="text-2xl font-bold">Rapport de classement archivistique</h1>
        <p className="mt-1 text-base">{currentName || csvFilename || "Sans titre"}</p>
        <p className="mt-1 text-xs">
          Généré le {today} par ODACEA
          {promptVersionAudit
            ? ` · audit AUD-001 v${promptVersionAudit}${modelAudit ? ` (modèle ${modelAudit})` : ""}`
            : ""}
          {promptVersionClassement
            ? ` · classement CLA-001 v${promptVersionClassement}${modelClassement ? ` (modèle ${modelClassement})` : ""}`
            : ""}
        </p>
      </header>

      {/* Statistiques de conformité — en tête pour une lecture rapide. */}
      {csvFinal && (
        <section className="odacea-print-avoid-break mb-6">
          <h2 className="mb-2 text-lg font-bold">Statistiques de conformité</h2>
          <table className="w-full border-collapse text-sm">
            <tbody>
              <PrintRow label="Dossiers créés" value={String(nFolders)} />
              <PrintRow label="Fichiers classés" value={String(nItems)} />
              {stats && (
                <>
                  <PrintRow
                    label="Conformité au plan validé"
                    value={
                      !stats.planParsed
                        ? "Non mesurable (arborescence du plan illisible)"
                        : stats.planMatches
                          ? "Conforme — identique au plan d'audit"
                          : `${stats.foldersOffPlan.length} dossier(s) hors plan, ${stats.foldersMissing.length} non réalisé(s)`
                    }
                  />
                  {stats.foldersOffPlan.length > 0 && (
                    <PrintRow
                      label="Dossiers hors plan"
                      value={stats.foldersOffPlan.join(", ")}
                    />
                  )}
                  {stats.foldersMissing.length > 0 && (
                    <PrintRow
                      label="Dossiers du plan non réalisés"
                      value={stats.foldersMissing.join(", ")}
                    />
                  )}
                  {stats.itemsMalformed > 0 && (
                    <PrintRow
                      label="Cibles malformées rattachées à la racine"
                      value={String(stats.itemsMalformed)}
                    />
                  )}
                </>
              )}
            </tbody>
          </table>
          {csvFinal.warnings.length > 0 && (
            <p className="mt-2 text-xs">
              {csvFinal.warnings.length} avertissement(s) de conversion — voir le
              détail dans l&apos;application.
            </p>
          )}
        </section>
      )}

      {/* Plan de classement — arbre lisible. */}
      {planModel && (
        <section className="mb-6">
          <h2 className="mb-2 text-lg font-bold">Plan de classement</h2>
          <p className="mb-1 font-semibold">{planModel.rootTitle}</p>
          <ul className="ml-1">
            {planModel.nodes.map((node, i) => (
              <PrintPlanNode key={i} node={node} numberParts={[i + 1]} />
            ))}
          </ul>
        </section>
      )}

      {/* Rapport d'audit complet (sauf mode plan seul). */}
      {!briefMode && rapportAudit && (
        <section className="mb-6">
          <h2 className="mb-2 text-lg font-bold">Rapport d&apos;audit</h2>
          <StreamingMarkdown text={stripStructureMarkers(rapportAudit)} />
        </section>
      )}

      {!briefMode && planNotes && (
        <section className="mb-6">
          <h2 className="mb-2 text-lg font-bold">Notes pour l&apos;archiviste</h2>
          <StreamingMarkdown text={stripStructureMarkers(planNotes)} />
        </section>
      )}
    </div>
  );
}

function PrintRow({ label, value }: { label: string; value: string }) {
  return (
    <tr className="border-b border-black/15">
      <th
        scope="row"
        className="w-1/3 py-1 pr-3 text-left align-top font-medium"
      >
        {label}
      </th>
      <td className="py-1 align-top">{value}</td>
    </tr>
  );
}

function PrintPlanNode({
  node,
  numberParts,
}: {
  node: PlanNode;
  numberParts: number[];
}) {
  const number = numberParts.join(".");
  return (
    <li className="odacea-print-avoid-break my-0.5 list-none">
      <span className="font-medium">
        {number}. {node.title}
      </span>{" "}
      <span className="font-mono text-xs text-black/60">
        {numberParts.join("-")}_{node.slug}/
      </span>
      {node.children.length > 0 && (
        <ul className="ml-5">
          {node.children.map((child, i) => (
            <PrintPlanNode
              key={i}
              node={child}
              numberParts={[...numberParts, i + 1]}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
