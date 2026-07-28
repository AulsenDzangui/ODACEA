"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { GithubIcon } from "@/components/github-icon";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { useNewProject } from "@/lib/use-new-project";

export function AppHeader({
  children,
  badge,
}: {
  children?: React.ReactNode;
  badge?: React.ReactNode;
}) {
  const pathname = usePathname();
  const onHome = pathname === "/";
  const { hasUnsaved, startNewProject } = useNewProject();
  const [confirmNew, setConfirmNew] = useState(false);

  // Sur la page d'accueil, cliquer le logo = « nouveau projet » : on réinitialise
  // le store (sinon l'URL retombe sur `/` mais l'interface garde le projet
  // chargé). Ailleurs (docs, tableau de bord), le logo reste un simple lien de
  // retour à l'accueil qui préserve le projet en cours.
  const handleLogo = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (!onHome) return;
    e.preventDefault();
    if (hasUnsaved) setConfirmNew(true);
    else startNewProject();
  };

  return (
    <div className="border-b border-(--ink-100) px-6 py-3 dark:border-zinc-800">
      {onHome && (
        <ConfirmDialog
          open={confirmNew}
          onOpenChange={setConfirmNew}
          title="Démarrer un nouveau projet ?"
          description="Le projet en cours n'a pas été sauvegardé et sera perdu. Cette action est irréversible."
          confirmLabel="Continuer"
          onConfirm={startNewProject}
        />
      )}
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
        <Link
          href="/"
          title="Outil Documentaire d'Audit, de Classement et d'Évaluation d'Archives"
          className="odacea-title hover:opacity-70 transition-opacity"
          onClick={handleLogo}
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
