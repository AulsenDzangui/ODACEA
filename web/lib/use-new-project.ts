"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { useWizard } from "@/lib/store";

/**
 * Logique partagée du « nouveau projet » (bouton de la sidebar + logo ODACEA du
 * header). `reset()` efface données **et** identité (stem/nom) dans le store,
 * puis l'URL est ramenée à `/` (dépose `?p=<stem>`) — sinon l'URL change mais
 * l'interface garde le projet chargé.
 *
 * `hasUnsaved` = un upload non encore matérialisé en projet (CSV chargé mais
 * audit pas lancé → aucun `currentStem`). Un projet matérialisé est
 * auto-sauvegardé : on peut le quitter sans avertir.
 */
export function useNewProject() {
  const router = useRouter();
  const reset = useWizard((s) => s.reset);
  const currentStem = useWizard((s) => s.currentStem);
  const csvOriginal = useWizard((s) => s.csvOriginal);
  const rapportAudit = useWizard((s) => s.rapportAudit);

  const hasUnsaved =
    (csvOriginal !== null || Boolean(rapportAudit)) && !currentStem;

  const startNewProject = useCallback(() => {
    reset();
    router.replace("/");
  }, [reset, router]);

  return { hasUnsaved, startNewProject };
}
