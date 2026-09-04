"use client";

import type { ComponentType, ReactNode } from "react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";

/**
 * Divulgation progressive (présentation seule) : enveloppe un bloc
 * d'options/outils avancés dans un accordéon replié par défaut, pour que les
 * écrans du wizard n'affichent en clair que le chemin simple. Factorise le
 * pattern jusqu'ici dupliqué au cas par cas (`EnrichPanel`, `FolderImportPanel`,
 * « Pour aller plus loin » de `step-classement.tsx`).
 *
 * Pas de persistance de l'état ouvert/fermé : `useState` local à l'accordéon
 * (remis à zéro à chaque montage), aucun ajout au store Zustand.
 *
 * Règle d'usage : ne jamais rendre une `AdvancedSection` dont tout le contenu
 * serait vide (ex. en mode démonstration) — gater le composant lui-même côté
 * appelant, pas seulement ses enfants.
 */
export function AdvancedSection({
  title,
  icon: Icon,
  badge,
  defaultOpen = false,
  children,
}: {
  title: ReactNode;
  icon?: ComponentType<{ className?: string }>;
  badge?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <Accordion
      type="single"
      collapsible
      defaultValue={defaultOpen ? "advanced" : undefined}
    >
      <AccordionItem value="advanced">
        <AccordionTrigger>
          <span className="flex items-center gap-2">
            {Icon && <Icon className="h-4 w-4 text-(--ink-500)" />}
            {title}
            {badge != null && (
              <Badge variant="secondary" className="ml-1">
                {badge}
              </Badge>
            )}
          </span>
        </AccordionTrigger>
        <AccordionContent>
          <div className="space-y-4 pt-1">{children}</div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
