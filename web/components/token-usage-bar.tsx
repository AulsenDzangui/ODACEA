import type { LlmUsage } from "@/lib/llm/client-stream";
import { formatDuration, formatTokens } from "@/lib/tokens/estimate";

/** Affiche la durée de traitement réelle d'une étape (mesure de performance).
 *  Indépendant de `TokenUsageBar` : un serveur local (Ollama, LM Studio) renvoie
 *  souvent la durée sans le décompte de tokens — la durée reste alors la seule
 *  mesure disponible. `null`/0 → rien n'est rendu. */
export function DurationBar({
  durationMs,
  label,
}: {
  durationMs: number | null | undefined;
  label?: string;
}) {
  if (!durationMs || durationMs <= 0) return null;
  return (
    <p className="text-xs text-(--ink-400)">
      {label && <span className="font-medium">{label} — </span>}
      traité en{" "}
      <span className="font-medium text-(--ink-500)">{formatDuration(durationMs)}</span>
    </p>
  );
}

export function TokenUsageBar({
  usage,
  durationMs,
  label,
}: {
  usage: LlmUsage | null | undefined;
  durationMs?: number | null;
  label?: string;
}) {
  const hasTokens = !!usage?.totalTokens;
  const hasDuration = !!durationMs && durationMs > 0;
  if (!hasTokens && !hasDuration) return null;

  const parts: string[] = [];
  if (hasTokens) {
    if (usage!.inputTokens != null) parts.push(`entrée : ${formatTokens(usage!.inputTokens)}`);
    if (usage!.outputTokens != null) parts.push(`sortie : ${formatTokens(usage!.outputTokens)}`);
    const cacheRead = usage!.inputDetails?.cacheReadTokens;
    if (cacheRead) parts.push(`cache : ${formatTokens(cacheRead)}`);
    const thinking = usage!.outputDetails?.reasoningTokens;
    if (thinking) parts.push(`thinking : ${formatTokens(thinking)}`);
  }

  return (
    <p className="text-xs text-(--ink-400)">
      {label && <span className="font-medium">{label} — </span>}
      {hasTokens && (
        <>
          <span className="font-medium text-(--ink-500)">{formatTokens(usage!.totalTokens!)}</span> tokens réels
          {parts.length > 0 && <span> ({parts.join(" · ")})</span>}
        </>
      )}
      {!hasTokens && hasDuration && (
        <>traité en <span className="font-medium text-(--ink-500)">{formatDuration(durationMs!)}</span></>
      )}
      {hasTokens && hasDuration && (
        <>. Traité en <span className="font-medium text-(--ink-500)">{formatDuration(durationMs!)}</span></>
      )}
    </p>
  );
}

export function sumUsage(
  usages: (LlmUsage | null | undefined)[],
): LlmUsage | null {
  const filtered = usages.filter((u): u is LlmUsage => u != null && !!u.totalTokens);
  if (filtered.length === 0) return null;
  return filtered.reduce<LlmUsage>(
    (acc, u) => ({
      inputTokens: (acc.inputTokens ?? 0) + (u.inputTokens ?? 0),
      outputTokens: (acc.outputTokens ?? 0) + (u.outputTokens ?? 0),
      totalTokens: (acc.totalTokens ?? 0) + (u.totalTokens ?? 0),
      inputDetails: {
        cacheReadTokens:
          (acc.inputDetails?.cacheReadTokens ?? 0) + (u.inputDetails?.cacheReadTokens ?? 0),
        cacheWriteTokens:
          (acc.inputDetails?.cacheWriteTokens ?? 0) + (u.inputDetails?.cacheWriteTokens ?? 0),
      },
      outputDetails: {
        reasoningTokens:
          (acc.outputDetails?.reasoningTokens ?? 0) + (u.outputDetails?.reasoningTokens ?? 0),
      },
    }),
    {},
  );
}
