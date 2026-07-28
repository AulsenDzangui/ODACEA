"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useWizard } from "@/lib/store";
import { Sidebar } from "@/components/sidebar";
import { SettingsModal } from "@/components/settings-modal";
import { AgentModal } from "@/components/agent/agent-modal";
import { Breadcrumb } from "@/components/breadcrumb";
import { StatusPill, BackendDownBanner } from "@/components/status-bar";
import { StepUpload } from "@/components/wizard/step-upload";
import { StepAudit } from "@/components/wizard/step-audit";
import { StepClassement } from "@/components/wizard/step-classement";
import { AppHeader } from "@/components/app-header";
import { PrintReport } from "@/components/print-report";
import { STEP_ACTIONS_FOOTER_ID } from "@/components/wizard/step-actions";
import { DEMO_MODE } from "@/lib/llm/config";
import { Button } from "@/components/ui/button";
import { Menu, BookOpen, PanelLeft, Settings, ShieldCheck, BarChart3, MessageSquare } from "lucide-react";

const SIDEBAR_COLLAPSED_KEY = "odacea-sidebar-collapsed";

export default function Home() {
  const step = useWizard((s) => s.step);
  // Identité du projet courant : sert de `key` à l'étape de classement. Charger
  // un autre projet alors qu'on y est déjà doit la remonter, sinon son état
  // local (lots du classement, repris ou en cours) resterait celui du projet
  // précédent — et une relance de lot viserait le mauvais fonds. Les deux
  // premières étapes n'ont pas de clé : le projet est matérialisé pendant
  // l'étape d'audit (au premier rapport), les remonter reviendrait à effacer la
  // démarche streamée à l'instant même où elle vient d'aboutir.
  const currentStem = useWizard((s) => s.currentStem);
  const setSettingsModalOpen = useWizard((s) => s.setSettingsModalOpen);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [agentModalOpen, setAgentModalOpen] = useState(false);

  const closeMobile = () => setMobileOpen(false);

  // Restaure l'état réduit après le mount (localStorage absent côté serveur).
  const collapsedHydrated = useRef(false);
  useEffect(() => {
    if (collapsedHydrated.current) return;
    collapsedHydrated.current = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1") setCollapsed(true);
  }, []);

  const persistCollapsed = (next: boolean) => {
    setCollapsed(next);
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
  };

  return (
    <>
    {/* Coquille applicative — masquée à l'impression (cf. PrintReport, D6). */}
    <div className="flex h-screen flex-col overflow-hidden print:hidden">
      <AppHeader badge={<StatusPill />}>
        <Button asChild variant="ghost" size="default" title="Documentation">
          <Link href="/docs">
            <BookOpen className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Documentation</span>
          </Link>
        </Button>
        {/* Agent : modale plutôt que page dédiée, toujours
            disponible sans quitter l'étape en cours. Masqué en démo — le
            backend le refuse (agt_disabled, état de session serveur). */}
        {!DEMO_MODE && (
          <Button
            variant="ghost"
            size="default"
            title="Agent"
            onClick={() => setAgentModalOpen(true)}
          >
            <MessageSquare className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Agent</span>
          </Button>
        )}
        <Button
          asChild
          variant="ghost"
          size="default"
          title="Statistiques de projets"
        >
          <Link href="/tableau-de-bord">
            <BarChart3 className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Statistiques</span>
          </Link>
        </Button>
        <Button
          variant="ghost"
          size="icon-lg"
          className="md:hidden"
          onClick={() => setMobileOpen(true)}
          aria-label="Ouvrir le menu"
        >
          <Menu className="h-5 w-5" />
        </Button>
      </AppHeader>
      <div className="flex min-h-0 flex-1">
        {/* Desktop sidebar : panneau complet ↔ rail d'icônes (largeur animée).
            Les deux vues restent montées pour permettre la transition ; la vue
            masquée est rendue inerte (ni focus ni interaction). */}
        <div className="hidden md:flex">
          <div
            inert={collapsed}
            className={`flex overflow-hidden transition-[width] duration-300 ease-in-out ${
              collapsed ? "w-0" : "w-80"
            }`}
          >
            <Suspense
              fallback={
                <aside className="w-80 shrink-0 border-r border-(--ink-200) bg-(--paper-100) p-5" />
              }
            >
              <Sidebar onCollapse={() => persistCollapsed(true)} />
            </Suspense>
          </div>
          <div
            inert={!collapsed}
            className={`flex overflow-hidden transition-[width] duration-300 ease-in-out ${
              collapsed ? "w-14" : "w-0"
            }`}
          >
            <IconRail
              onExpand={() => persistCollapsed(false)}
              onOpenSettings={() => setSettingsModalOpen(true)}
            />
          </div>
        </div>

        {/* Mobile drawer */}
        {mobileOpen && (
          <>
            <button
              type="button"
              aria-label="Fermer"
              className="fixed inset-0 z-40 bg-black/40 md:hidden"
              onClick={closeMobile}
            />
            <div className="fixed inset-y-0 left-0 z-50 flex w-80 max-w-[85vw] bg-(--paper-100) shadow-xl md:hidden">
              <Suspense fallback={null}>
                <Sidebar onCollapse={closeMobile} />
              </Suspense>
            </div>
          </>
        )}

        {/* Colonne de droite : breadcrumb (fixe, en tête) + contenu scrollable.
            Le breadcrumb est ici borné à la zone de contenu, la sidebar démarre
            donc juste sous le header et occupe toute la hauteur. */}
        <div className="relative flex min-w-0 flex-1 flex-col">
          {DEMO_MODE && (
            <div className="flex items-center justify-center gap-2 border-b border-(--ink-100) bg-(--paper-100) px-4 py-1.5 text-center text-xs text-(--ink-600) dark:border-zinc-800 dark:bg-zinc-900">
              <ShieldCheck className="h-3.5 w-3.5 shrink-0" />
              <span>
                Démonstration publique · jeu de données et modèle imposés · 1 essai
                par visiteur et par jour · aucune donnée conservée
              </span>
            </div>
          )}
          <div className="shrink-0 overflow-x-hidden">
            <BackendDownBanner />
          </div>
          <Breadcrumb />
          {/* pb-24 : réserve la place du pied flottant pour que le dernier
              contenu se dégage de la barre une fois entièrement déroulé. */}
          <main className="min-w-0 flex-1 overflow-y-auto px-6 pt-6 pb-24">
            <div className="mx-auto max-w-6xl">
              {step === "upload" && <StepUpload />}
              {step === "audit" && <StepAudit />}
              {step === "classement" && <StepClassement key={currentStem} />}
            </div>
          </main>
          {/* Pied d'actions : superposé en bas de la colonne (pleine largeur),
              le contenu défile dessous → l'effet verre dépoli est visible. Les
              étapes y injectent leurs CTA via <StepActions> (portail). Vide →
              invisible. */}
          <div
            id={STEP_ACTIONS_FOOTER_ID}
            className="pointer-events-none absolute inset-x-0 bottom-0 z-20 overflow-x-hidden *:pointer-events-auto"
          />
        </div>
      </div>

      <SettingsModal />
      <AgentModal open={agentModalOpen} onOpenChange={setAgentModalOpen} />
    </div>
    <PrintReport />
    </>
  );
}

// Rail d'icônes affiché quand le panneau est réduit. Le premier bouton ré-affiche
// le panneau (projets) ; le second ouvre la modale de réglages.
function IconRail({
  onExpand,
  onOpenSettings,
}: {
  onExpand: () => void;
  onOpenSettings: () => void;
}) {
  return (
    <div className="flex w-14 shrink-0 flex-col items-center gap-1 border-r border-(--ink-100) bg-(--paper-100) py-3 dark:border-zinc-800 dark:bg-zinc-900">
      <button
        type="button"
        onClick={onExpand}
        aria-label="Afficher le panneau"
        aria-expanded={false}
        title="Afficher le panneau"
        className="flex h-9 w-9 items-center justify-center rounded-md text-(--ink-600) hover:bg-(--ink-100) hover:text-(--ink-800) focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <PanelLeft className="h-4 w-4" />
      </button>
      {/* Réglages épinglé en bas, en miroir du pied de la sidebar dépliée. */}
      <button
        type="button"
        onClick={onOpenSettings}
        aria-label="Réglages"
        title="Réglages"
        className="mt-auto flex h-9 w-9 items-center justify-center rounded-md text-(--ink-500) hover:bg-(--ink-100) hover:text-(--ink-800) focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <Settings className="h-4 w-4" />
      </button>
    </div>
  );
}
