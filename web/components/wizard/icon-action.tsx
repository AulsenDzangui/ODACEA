import type { ComponentType } from "react";
import { Button } from "@/components/ui/button";

/**
 * Bouton-icône carré pour une action utilitaire secondaire, avec infobulle
 * native du navigateur (`title`) et `aria-label`. Utilisé pour regrouper les
 * actions à droite d'un bouton primaire, sans empiler des boutons pleine
 * largeur.
 */
export function IconAction({
  label,
  icon: Icon,
  onClick,
  variant = "outline",
}: {
  label: string;
  icon: ComponentType<{ className?: string }>;
  onClick: () => void;
  variant?: "outline" | "destructive" | "ghost";
}) {
  return (
    <Button
      variant={variant}
      size="icon-lg"
      className="size-10"
      onClick={onClick}
      title={label}
      aria-label={label}
    >
      <Icon className="h-4 w-4" />
    </Button>
  );
}
