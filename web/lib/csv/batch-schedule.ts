// Ordonnancement des lots CLA-001 — parallélisme borné côté front,
// et reprise d'un classement interrompu.
//
// Le moteur (CLI/API) est sans état : chaque `/classement/batch` re-dérive sa
// tranche indépendamment, donc N lots peuvent être en vol simultanément sans
// coordination serveur. Ce module ne porte que la *décision* de concurrence et
// la boucle d'ordonnancement — la logique métier (conversion RESIP, IDs, dates)
// reste côté Python. Miroir de la sémantique du CLI `--concurrency`
// (`backend/cli.py::_resolve_concurrency`) : séquentiel par défaut, borné, et
// **forcé séquentiel pour un serveur local** (mono-requête).

import type { ClassementBatch } from "@/lib/csv/types";

/** Plafond de lots en vol (identique à `MAX_CONCURRENCY` du moteur). */
export const MAX_CLASSEMENT_CONCURRENCY = 4;

/** Nombre de lots à traiter en parallèle, effectivement appliqué.
 *
 *  - `isLocal` ⇒ 1 : un serveur local (Ollama/LM Studio) traite une requête à la
 *    fois ; paralléliser les sérialiserait, voire saturerait la machine.
 *  - sinon borné à `[1, MAX_CLASSEMENT_CONCURRENCY]` et jamais au-delà du nombre
 *    de lots (inutile d'ouvrir plus de workers que de tâches). */
export function resolveConcurrency(
  requested: number,
  isLocal: boolean,
  nBatches: number,
): number {
  if (isLocal) return 1;
  const bounded = Math.min(
    Math.max(1, Math.floor(requested) || 1),
    MAX_CLASSEMENT_CONCURRENCY,
  );
  return Math.max(1, Math.min(bounded, nBatches));
}

/** Traite les index `[0, nTasks)` avec au plus `concurrency` exécutions de `task`
 *  en vol. `task(i)` ne doit jamais rejeter (les erreurs par lot sont capturées
 *  dans l'état du lot en amont) ; `shouldStop()` interrompt l'attribution de
 *  nouveaux index (annulation utilisateur). Les tâches démarrent dans l'ordre
 *  croissant ; leur ordre d'achèvement n'est pas garanti (la finalisation
 *  réassemble par index, indépendante de cet ordre). */
export async function runBatchPool(
  nTasks: number,
  concurrency: number,
  task: (i: number) => Promise<void>,
  shouldStop: () => boolean = () => false,
): Promise<void> {
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < nTasks) {
      if (shouldStop()) return;
      const i = next++;
      await task(i);
    }
  };
  const workers = Array.from(
    { length: Math.max(1, Math.min(concurrency, nTasks)) },
    worker,
  );
  await Promise.all(workers);
}

// ── Reprise d'un classement interrompu ───────────────────────────────────────
// Les lots achevés sont persistés au projet **au fil de l'eau** ; à la
// réouverture, un classement incomplet doit pouvoir être repris *sur le reste*
// plutôt que repayé en entier. La reprise n'est légitime que si le découpage
// courant redonne exactement les mêmes tranches qu'au run interrompu : le moteur
// étant sans état, `batchIndex` ne désigne la bonne tranche que pour un même
// corpus et une même taille de lot (`api/engine.py::batch_stream` re-dérive les
// items à chaque appel). Deux gardes complémentaires : le découpage
// (`resumableBatches`, hors ligne) et le corpus (`resumeStillValid`, qui a
// besoin du total re-dérivé par `/classement/prepare`).

/** Libellé d'un lot laissé inachevé par une session interrompue. */
export const BATCH_INTERRUPTED = "Lot interrompu (session précédente)";

/** Lots réutilisables d'un run interrompu, ou `null` si rien n'est à reprendre.
 *
 *  Normalise le statut : tout lot non abouti (erreur, jamais lancé, interrompu
 *  en vol) redevient « en erreur », donc relançable par l'UI de relance
 *  existante. Renvoie `null` si tous les lots sont aboutis (rien à reprendre) ou
 *  si la taille de lot a changé depuis — auquel cas l'index ne désignerait plus
 *  la même tranche et la reprise corromprait le classement. */
export function resumableBatches(
  persisted: ClassementBatch[] | null | undefined,
  batchSize: number,
): ClassementBatch[] | null {
  if (!persisted || persisted.length === 0) return null;
  const normalized = persisted.map((b): ClassementBatch => {
    // Rétro-compat : les projets antérieurs n'ont pas de `status` et ne
    // contiennent que des lots aboutis (rien n'était persisté avant la fin).
    const done = (b.status ?? "done") === "done" && b.rows.length > 0;
    return done
      ? { ...b, status: "done", error: undefined }
      : { ...b, status: "error", rows: [], error: b.error || BATCH_INTERRUPTED };
  });
  if (normalized.every((b) => b.status === "done")) return null;
  const last = normalized[normalized.length - 1];
  const headMatches = normalized
    .slice(0, -1)
    .every((b) => b.itemCount === batchSize);
  if (!headMatches || last.itemCount > batchSize) return null;
  return normalized;
}

/** Le corpus est-il resté celui du run interrompu ? Les options de préparation
 *  sont des réglages **globaux** (non liés au projet) : elles ont pu changer
 *  entre deux sessions et modifier le jeu d'items, donc les tranches. À vérifier
 *  avec le total re-dérivé par le moteur avant de relancer un lot par index. */
export function resumeStillValid(
  batches: { itemCount: number }[],
  total: number,
): boolean {
  return batches.reduce((n, b) => n + b.itemCount, 0) === total;
}
