import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Suffixe d'accord pluriel français : "s" dès que n ≥ 2, "" sinon (0 et 1 =
 *  singulier). Renvoie un suffixe plutôt qu'un mot pour couvrir les accords
 *  multiples d'une même phrase : `item${plS(n)} envoyé${plS(n)}`. */
export const plS = (n: number) => (n >= 2 ? "s" : "")
