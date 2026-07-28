import { beforeEach, describe, expect, it } from "vitest";

// localStorage minimal en mémoire — même mock que persistence.test.ts.
class MemoryStorage {
  private map = new Map<string, string>();
  get length() {
    return this.map.size;
  }
  key(i: number) {
    return [...this.map.keys()][i] ?? null;
  }
  getItem(k: string) {
    return this.map.has(k) ? this.map.get(k)! : null;
  }
  setItem(k: string, v: string) {
    this.map.set(k, String(v));
  }
  removeItem(k: string) {
    this.map.delete(k);
  }
  clear() {
    this.map.clear();
  }
}

// @ts-expect-error — installe un faux window pour les modules client.
globalThis.window = { localStorage: new MemoryStorage() };

const { computeProjectMetrics, aggregateFonds } = await import(
  "@/lib/fonds-stats"
);
const { saveProject, listProjectMetrics } = await import("@/lib/persistence");

type SnapshotArg = Parameters<typeof saveProject>[1];

const baseSnapshot = (over: Partial<SnapshotArg> = {}): SnapshotArg =>
  ({
    csvFilename: "vrac.csv",
    csvOriginal: [
      { ID: "1", File: ".", "Content.DescriptionLevel": "RecordGrp" },
      { ID: "2", File: "a.pdf", "Content.DescriptionLevel": "Item" },
      { ID: "3", File: "b.pdf", "Content.DescriptionLevel": "Item" },
    ],
    archivisteObservation: "",
    step: "audit" as const,
    rapportAudit: "",
    thinkingAudit: "",
    planValide: "",
    planValideOriginal: "",
    planNotes: "",
    planModifie: false,
    briefMode: false,
    thinkingClassement: "",
    llmRawResponse: "",
    llmRawRows: null,
    classementBatches: null,
    csvFinal: null,
    lastError: "",
    ...over,
  }) as SnapshotArg;

const finalResult = (planMatches: boolean, foldersOffPlan: string[] = []) => ({
  rows: [
    { ID: "1", File: ".", "Content.DescriptionLevel": "RecordGrp" },
    { ID: "2", File: "x", "Content.DescriptionLevel": "RecordGrp" },
    { ID: "3", File: "a.pdf", "Content.DescriptionLevel": "Item" },
    { ID: "4", File: "b.pdf", "Content.DescriptionLevel": "Item" },
  ],
  columns: [],
  warnings: [],
  stats: {
    planParsed: true,
    planFolders: 2,
    outputFolders: 2,
    foldersOffPlan,
    foldersMissing: [],
    itemsMalformed: 0,
    planMatches,
  },
});

describe("computeProjectMetrics", () => {
  it("compte les Item du CSV d'origine (volume) et laisse le reste null avant classement", () => {
    const m = computeProjectMetrics(baseSnapshot());
    expect(m.itemCount).toBe(2);
    expect(m.classifiedCount).toBeNull();
    expect(m.planParsed).toBeNull();
    expect(m.planMatches).toBeNull();
    expect(m.completed).toBe(false);
    expect(m.step).toBe("audit");
  });

  it("dérive la conformité depuis les stats moteur persistées (pas de recalcul)", () => {
    const m = computeProjectMetrics(
      baseSnapshot({
        step: "classement",
        csvFinal: finalResult(false, ["Divers", "A_trier"]),
      }),
    );
    expect(m.classifiedCount).toBe(2);
    expect(m.planParsed).toBe(true);
    expect(m.planMatches).toBe(false);
    expect(m.foldersOffPlan).toBe(2);
    expect(m.completed).toBe(true);
  });

  it("additionne durées et tokens des deux agents, null si rien mesuré", () => {
    const m = computeProjectMetrics(
      baseSnapshot({
        durationAudit: 1000,
        durationClassementTotal: 2500,
        usageAudit: { totalTokens: 800 },
        usageClassementTotal: { totalTokens: 1200 },
      }),
    );
    expect(m.durationTotalMs).toBe(3500);
    expect(m.totalTokens).toBe(2000);

    const empty = computeProjectMetrics(baseSnapshot());
    expect(empty.durationTotalMs).toBeNull();
    expect(empty.totalTokens).toBeNull();
  });
});

describe("aggregateFonds", () => {
  it("somme les volumes et calcule le taux de conformité sur les projets mesurés", () => {
    const metrics = [
      computeProjectMetrics(
        baseSnapshot({ csvFinal: finalResult(true), durationAudit: 1000 }),
      ),
      computeProjectMetrics(
        baseSnapshot({
          csvFinal: finalResult(false, ["Divers"]),
          durationClassementTotal: 2000,
        }),
      ),
      // Projet non classé : compte au volume mais pas à la conformité.
      computeProjectMetrics(baseSnapshot()),
    ];
    const agg = aggregateFonds(metrics);
    expect(agg.projectCount).toBe(3);
    expect(agg.completedCount).toBe(2);
    expect(agg.totalItems).toBe(6); // 2 + 2 + 2
    expect(agg.totalClassified).toBe(4); // 2 + 2 + 0
    expect(agg.conformityMeasured).toBe(2);
    expect(agg.conformityMatching).toBe(1);
    expect(agg.conformityRate).toBeCloseTo(0.5);
    expect(agg.totalDurationMs).toBe(3000);
    expect(agg.totalFoldersOffPlan).toBe(1);
  });

  it("taux de conformité null quand aucun projet n'a de plan mesuré", () => {
    const agg = aggregateFonds([computeProjectMetrics(baseSnapshot())]);
    expect(agg.conformityMeasured).toBe(0);
    expect(agg.conformityRate).toBeNull();
  });
});

describe("intégration persistance", () => {
  beforeEach(() => {
    (window.localStorage as unknown as MemoryStorage).clear();
  });

  it("saveProject fige les mesures dans l'index, listProjectMetrics les lit", () => {
    saveProject("Fonds RH", baseSnapshot({ csvFinal: finalResult(true) }));
    const list = listProjectMetrics();
    expect(list).toHaveLength(1);
    expect(list[0].entry.metrics).toBeDefined();
    expect(list[0].metrics?.itemCount).toBe(2);
    expect(list[0].metrics?.planMatches).toBe(true);
  });

  it("recalcule les mesures pour un projet d'index antérieur aux mesures (rétro-compat)", () => {
    // Simule l'état laissé par une version sans mesures : projet stocké + entrée
    // d'index dépourvue de `metrics`.
    saveProject("Ancien", baseSnapshot({ csvFinal: finalResult(false, ["X"]) }));
    const idx = JSON.parse(
      window.localStorage.getItem("odacea-projects/index")!,
    ) as { stem: string; metrics?: unknown }[];
    delete idx[0].metrics;
    window.localStorage.setItem(
      "odacea-projects/index",
      JSON.stringify(idx),
    );

    const list = listProjectMetrics();
    expect(list[0].entry.metrics).toBeUndefined();
    // Recalculé à la volée depuis le projet rechargé.
    expect(list[0].metrics?.foldersOffPlan).toBe(1);
    expect(list[0].metrics?.completed).toBe(true);
  });
});
