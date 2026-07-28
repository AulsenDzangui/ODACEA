// Tests unitaires : stringifyCsv (sérialisation téléchargement) et le
// store Zustand (applyProjectSnapshot / resets).
import { beforeEach, describe, expect, it } from "vitest";

import { stringifyCsv } from "@/lib/csv/parse";
import { useWizard, type ProjectSnapshot } from "@/lib/store";

// ── stringifyCsv ─────────────────────────────────────────────────────────────

describe("stringifyCsv", () => {
  it("sérialise en ; avec QUOTE_ALL (aligné sortie Python)", () => {
    const rows = [
      { ID: "1", File: ".", "Content.Title": "Racine" },
      { ID: "2", File: "a/b.txt", "Content.Title": 'Avec "guillemets"' },
    ];
    expect(stringifyCsv(rows)).toBe(
      '"ID";"File";"Content.Title"\n' +
        '"1";".";"Racine"\n' +
        '"2";"a/b.txt";"Avec ""guillemets"""',
    );
  });

  it("respecte l'ordre de colonnes fourni et comble les champs absents", () => {
    const rows = [{ B: "2", A: "1" }];
    expect(stringifyCsv(rows, ["A", "B", "C"])).toBe('"A";"B";"C"\n"1";"2";""');
  });

  it("liste vide : en-tête seul (ou vide sans colonnes)", () => {
    expect(stringifyCsv([], ["A"])).toBe('"A"');
    expect(stringifyCsv([])).toBe("");
  });
});

// ── Store Zustand ────────────────────────────────────────────────────────────

function makeSnapshot(): ProjectSnapshot {
  return {
    csvFilename: "vrac.csv",
    csvOriginal: [{ ID: "1", File: "." }],
    archivisteObservation: "note",
    step: "classement",
    rapportAudit: "# Rapport",
    thinkingAudit: "pensées",
    planValide: "plan → 1_X/",
    planValideOriginal: "plan → 1_X/",
    planNotes: "notes",
    planModifie: false,
    briefMode: true,
    referencePlan: "```text\nFonds → F/\n```",
    referencePlanName: "dossiers.csv",
    referenceMode: "conform",
    thinkingClassement: "",
    llmRawResponse: "raw",
    llmRawRows: [{ Path: "a", TargetFolder: "1_X", NewTitle: "a" }],
    classementBatches: null,
    csvFinal: null,
    lastError: "",
    usageAudit: { totalTokens: 100 },
    durationAudit: 1234,
  };
}

describe("useWizard.applyProjectSnapshot", () => {
  beforeEach(() => {
    // Repart d'un état neuf entre les tests (store module-level).
    useWizard.getState().reset();
  });

  it("hydrate l'état complet et pose l'identité du projet atomiquement", () => {
    useWizard.getState().applyProjectSnapshot(makeSnapshot(), "vrac", "Mon vrac");
    const s = useWizard.getState();
    expect(s.step).toBe("classement");
    expect(s.csvFilename).toBe("vrac.csv");
    expect(s.csvOriginal).toEqual([{ ID: "1", File: "." }]);
    expect(s.planValide).toBe("plan → 1_X/");
    expect(s.briefMode).toBe(true);
    // Plan de référence retenu pour l'audit restauré avec le projet.
    expect(s.referencePlan).toBe("```text\nFonds → F/\n```");
    expect(s.referencePlanName).toBe("dossiers.csv");
    expect(s.referenceMode).toBe("conform");
    expect(s.llmRawRows).toHaveLength(1);
    expect(s.currentStem).toBe("vrac");
    expect(s.currentName).toBe("Mon vrac");
    expect(s.usageAudit).toEqual({ totalTokens: 100 });
    expect(s.durationAudit).toBe(1234);
  });

  it("projets anciens : mesures absentes ramenées à null, briefMode à false", () => {
    const legacy = makeSnapshot();
    delete legacy.usageAudit;
    delete legacy.durationAudit;
    // briefMode absent des snapshots d'avant la fonctionnalité.
    (legacy as Partial<ProjectSnapshot>).briefMode = undefined;
    // Plan de référence absent des projets antérieurs → défauts.
    delete legacy.referencePlan;
    delete legacy.referencePlanName;
    delete legacy.referenceMode;
    useWizard.getState().applyProjectSnapshot(legacy, "vieux", "Vieux projet");
    const s = useWizard.getState();
    expect(s.usageAudit).toBeNull();
    expect(s.durationAudit).toBeNull();
    expect(s.briefMode).toBe(false);
    expect(s.referencePlan).toBe("");
    expect(s.referencePlanName).toBe("");
    expect(s.referenceMode).toBe("inspire");
  });
});

describe("useWizard.adoptPlan (plan fourni sans audit)", () => {
  beforeEach(() => {
    useWizard.getState().reset();
  });

  it("adopte le plan, marque l'origine « fourni » et n'invente aucune métadonnée d'audit", () => {
    // Simule un audit LLM préalable, puis l'adoption d'un plan fourni par-dessus.
    useWizard
      .getState()
      .setAuditResult("# Rapport", "pensées", "plan IA → 1_X/", "notes");
    useWizard.getState().setUsageAudit({ totalTokens: 999 });
    useWizard.getState().setPromptVersionAudit("2.0.0");
    useWizard.getState().setModelAudit("claude-opus-4-8");

    useWizard.getState().adoptPlan("plan fourni → 1_Y/");
    const s = useWizard.getState();
    expect(s.planValide).toBe("plan fourni → 1_Y/");
    expect(s.planValideOriginal).toBe("plan fourni → 1_Y/");
    expect(s.planOrigin).toBe("fourni");
    expect(s.planModifie).toBe(false);
    // Aucune métadonnée d'audit fabriquée : rapport/notes/usage/version/modèle vidés.
    expect(s.rapportAudit).toBe("");
    expect(s.planNotes).toBe("");
    expect(s.usageAudit).toBeNull();
    expect(s.promptVersionAudit).toBeNull();
    expect(s.modelAudit).toBeNull();
  });

  it("setAuditResult marque l'origine « audit_llm » quand un plan est produit", () => {
    useWizard.getState().setAuditResult("# R", "", "plan → 1_X/", "n");
    expect(useWizard.getState().planOrigin).toBe("audit_llm");
  });
});

describe("clé API : session-only par défaut", () => {
  beforeEach(() => {
    useWizard.getState().reset();
  });

  it("la mémorisation est désactivée par défaut", () => {
    expect(useWizard.getState().rememberApiKey).toBe(false);
  });

  it("la clé saisie reste disponible en mémoire pour la session", () => {
    useWizard.getState().setApiKey("sk-en-memoire");
    // Même sans mémorisation, la clé sert aux appels de la session courante.
    expect(useWizard.getState().apiKey).toBe("sk-en-memoire");
    expect(useWizard.getState().rememberApiKey).toBe(false);
  });

  it("setRememberApiKey bascule la préférence", () => {
    useWizard.getState().setRememberApiKey(true);
    expect(useWizard.getState().rememberApiKey).toBe(true);
    useWizard.getState().setRememberApiKey(false);
    expect(useWizard.getState().rememberApiKey).toBe(false);
  });
});
