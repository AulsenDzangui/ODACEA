"use client";

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Brain } from "lucide-react";

type Props = {
  thinking: string;
  defaultOpen?: boolean;
  title?: string;
};

export function ThinkingPanel({
  thinking,
  defaultOpen = false,
  title = "Raisonnement de l'IA",
}: Props) {
  if (!thinking.trim()) return null;

  return (
    <Accordion
      type="single"
      collapsible
      defaultValue={defaultOpen ? "thinking" : undefined}
    >
      <AccordionItem value="thinking">
        <AccordionTrigger>
          <div className="flex items-center gap-2">
            <Brain className="h-3.5 w-3.5" />
            <span>{title}</span>
            <span className="text-xs font-normal text-(--ink-500)">
              ({thinking.length.toLocaleString("fr-FR")} car.)
            </span>
          </div>
        </AccordionTrigger>
        <AccordionContent>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md border border-(--ink-100) bg-(--paper-100) p-3 font-mono text-xs text-(--ink-700)">
            {thinking}
          </pre>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
