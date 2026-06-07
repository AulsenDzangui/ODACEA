import Link from "next/link";
import { GithubIcon } from "@/components/github-icon";
import { Button } from "@/components/ui/button";

export function AppHeader({
  children,
  badge,
}: {
  children?: React.ReactNode;
  badge?: React.ReactNode;
}) {
  return (
    <div className="border-b border-(--ink-100) px-6 py-3 dark:border-zinc-800">
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
        <Link
          href="/"
          title="Outil Documentaire d'Audit et de Classement d'Archives Électroniques"
          className="odacea-title hover:opacity-70 transition-opacity"
        >
          ODACEA
        </Link>
        <div>{badge}</div>
        <div className="flex items-center justify-end gap-2">
          <Button asChild variant="ghost" size="icon-lg">
            <a
              href="https://github.com/AulsenDzangui/odacea"
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Code source sur GitHub"
              title="Code source sur GitHub"
            >
              <GithubIcon className="h-4 w-4" />
            </a>
          </Button>
          {children}
        </div>
      </div>
    </div>
  );
}
