"use client";

import { Info } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

// Bulle d'aide contextuelle : une icône « i » à côté d'un libellé, dont le
// contenu explicatif s'affiche au survol/focus. Remplace les paragraphes d'aide
// permanents pour alléger l'interface (motif déjà utilisé dans settings-modal).
export function InfoTip({
  label,
  children,
}: {
  // Décrit ce qu'explique la bulle — lu par les lecteurs d'écran (aria-label).
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className="inline-flex text-(--ink-400) hover:text-(--ink-600) focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <Info className="h-3.5 w-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent>{children}</TooltipContent>
    </Tooltip>
  );
}
