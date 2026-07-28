"use client";

import { useWizard, type WizardStep } from "@/lib/store";
import { useT } from "@/lib/i18n";

const ORDER: Record<WizardStep, number> = {
  upload: 1,
  audit: 2,
  classement: 3,
};

export function Breadcrumb() {
  const t = useT();
  const step = useWizard((s) => s.step);
  const csvOriginal = useWizard((s) => s.csvOriginal);
  const planValide = useWizard((s) => s.planValide);
  const setStep = useWizard((s) => s.setStep);

  const STEPS: { id: WizardStep; label: string }[] = [
    { id: "upload", label: t.breadcrumb.upload },
    { id: "audit", label: t.breadcrumb.audit },
    { id: "classement", label: t.breadcrumb.classement },
  ];

  const canNavigate = (target: WizardStep) => {
    if (target === "upload") return true;
    if (target === "audit") return csvOriginal !== null;
    if (target === "classement") return planValide !== "";
    return false;
  };

  return (
    <nav className="odacea-breadcrumb px-6" aria-label={t.breadcrumb.aria}>
      {STEPS.map((s, i) => {
        const currentIdx = ORDER[step];
        const sIdx = ORDER[s.id];
        const enabled = canNavigate(s.id);
        const inactive = !enabled || s.id === step;
        let cls: string;
        if (s.id === step) {
          cls = "odacea-step-active";
        } else if (sIdx < currentIdx) {
          cls = "odacea-step-done";
        } else {
          cls = enabled ? "odacea-step-done" : "odacea-step-future";
        }
        return (
          <span key={s.id} className="flex items-center gap-[0.55rem]">
            {/* On évite l'attribut `disabled` natif : Firefox le restaure/retire
                sur les contrôles de formulaire au rechargement (avant l'hydratation
                React), ce qui crée un mismatch d'hydratation (`disabled={null}`
                côté DOM vs `true` côté rendu). `aria-disabled` n'est pas concerné
                par cette restauration ; la navigation est bloquée via le onClick. */}
            <button
              type="button"
              aria-disabled={inactive}
              aria-current={s.id === step ? "step" : undefined}
              tabIndex={inactive ? -1 : 0}
              onClick={() => {
                if (enabled && s.id !== step) setStep(s.id);
              }}
              className={cls}
            >
              {s.label}
            </button>
            {i < STEPS.length - 1 && (
              <span className="odacea-step-sep">&rsaquo;</span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
