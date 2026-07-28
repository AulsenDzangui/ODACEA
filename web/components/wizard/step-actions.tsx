"use client";

import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Id du conteneur de pied rendu par `page.tsx`, hors de la zone scrollable. */
export const STEP_ACTIONS_FOOTER_ID = "step-actions-footer";

/**
 * Barre d'actions d'étape rendue dans le **pied de page** (`page.tsx`), via un
 * portail, plutôt qu'en fin de contenu.
 *
 * Le pied est un frère du `<main>` scrollable : il occupe toute la largeur de la
 * colonne de contenu et reste collé en bas sans jamais défiler. Le contenu de
 * l'étape glisse donc *sous* le pied et disparaît derrière (rien ne dépasse sur
 * les bords). Le portail laisse chaque étape définir ses propres boutons (états,
 * `disabled`, variantes) là où vit leur logique.
 *
 * Une seule `StepActions` est montée à la fois (vues d'étape mutuellement
 * exclusives) ; le pied reste vide — et invisible — tant qu'aucune n'est montée.
 */
export function StepActions({ children }: { children: ReactNode }) {
  // Le portail ne peut viser sa cible qu'après le montage client (le conteneur
  // de pied n'est dans le DOM qu'au commit). Synchro d'hydratation ponctuelle.
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSlot(document.getElementById(STEP_ACTIONS_FOOTER_ID));
  }, []);

  if (!slot) return null;

  return createPortal(
    <div className="flex items-center justify-center gap-2 border-t border-(--ink-200) bg-(--paper-50)/75 px-6 py-3 shadow-[0_-4px_12px_-8px_rgba(0,0,0,0.18)] backdrop-blur-md">
      {children}
    </div>,
    slot,
  );
}
