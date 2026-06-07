"use client";

import { useMemo, type MouseEvent } from "react";
import { extractToc } from "@/lib/markdown/toc";
import { List } from "lucide-react";

type Props = {
  text: string;
  className?: string;
};

const LEVEL_INDENT: Record<1 | 2 | 3 | 4, string> = {
  1: "pl-0",
  2: "pl-3",
  3: "pl-6",
  4: "pl-9",
};

export function MarkdownToc({ text, className }: Props) {
  const entries = useMemo(() => extractToc(text), [text]);

  if (entries.length === 0) return null;

  const handleClick = (e: MouseEvent<HTMLAnchorElement>, id: string) => {
    e.preventDefault();
    const target = document.getElementById(id);
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    if (typeof history !== "undefined" && history.replaceState) {
      history.replaceState(null, "", `#${id}`);
    }
  };

  return (
    <nav
      aria-label="Table des matières"
      className={
        "rounded-md border border-(--ink-100) bg-(--paper-100) p-3 " +
        (className ?? "")
      }
    >
      <p className="odacea-section-heading mb-2 flex items-center gap-1.5">
        <List className="h-3.5 w-3.5" />
        Table des matières
      </p>
      <ul className="space-y-1 text-xs">
        {entries.map((entry, i) => (
          <li
            key={`${entry.id}-${i}`}
            className={LEVEL_INDENT[entry.level]}
          >
            <a
              href={`#${entry.id}`}
              onClick={(e) => handleClick(e, entry.id)}
              className={
                "block truncate rounded px-1.5 py-1 text-(--ink-700) hover:bg-(--paper-200) hover:text-(--ink-900) " +
                (entry.level === 1 ? "font-semibold" : "")
              }
              title={entry.text}
            >
              {entry.text}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
