// Tests unitaires. ordonnancement des lots CLA-001 en parallèle.
// `resolveConcurrency` (décision de concurrence, miroir du CLI) et `runBatchPool`
// (boucle bornée). Transport/orchestration pure ; la logique métier reste Python.
import { describe, expect, it } from "vitest";

import {
  BATCH_INTERRUPTED,
  MAX_CLASSEMENT_CONCURRENCY,
  resolveConcurrency,
  resumableBatches,
  resumeStillValid,
  runBatchPool,
} from "@/lib/csv/batch-schedule";
import type { ClassementBatch } from "@/lib/csv/types";

describe("resolveConcurrency", () => {
  it("séquentiel par défaut (1 demandé → 1)", () => {
    expect(resolveConcurrency(1, false, 10)).toBe(1);
  });

  it("borne au plafond du moteur", () => {
    expect(resolveConcurrency(99, false, 10)).toBe(MAX_CLASSEMENT_CONCURRENCY);
  });

  it("ne dépasse jamais le nombre de lots", () => {
    expect(resolveConcurrency(4, false, 2)).toBe(2);
  });

  it("forcé séquentiel pour un serveur local, quelle que soit la demande", () => {
    expect(resolveConcurrency(4, true, 10)).toBe(1);
  });

  it("plancher à 1 sur une valeur invalide (0, NaN)", () => {
    expect(resolveConcurrency(0, false, 10)).toBe(1);
    expect(resolveConcurrency(Number.NaN, false, 10)).toBe(1);
  });
});

describe("runBatchPool", () => {
  it("exécute chaque index exactement une fois", async () => {
    const seen: number[] = [];
    await runBatchPool(5, 2, async (i) => {
      seen.push(i);
    });
    expect([...seen].sort((a, b) => a - b)).toEqual([0, 1, 2, 3, 4]);
  });

  it("démarre les tâches dans l'ordre croissant", async () => {
    const started: number[] = [];
    await runBatchPool(4, 2, async (i) => {
      started.push(i);
      await Promise.resolve();
    });
    // Les 2 premiers workers prennent 0 et 1 avant tout await.
    expect(started.slice(0, 2)).toEqual([0, 1]);
  });

  it("ne dépasse jamais la concurrence demandée (lots en vol)", async () => {
    let inFlight = 0;
    let peak = 0;
    await runBatchPool(6, 3, async () => {
      inFlight++;
      peak = Math.max(peak, inFlight);
      await new Promise((r) => setTimeout(r, 5));
      inFlight--;
    });
    // 6 tâches, 3 workers → au plus 3 en vol simultanément.
    expect(peak).toBe(3);
  });

  it("cesse d'attribuer de nouveaux lots quand shouldStop passe à vrai", async () => {
    const seen: number[] = [];
    let stop = false;
    await runBatchPool(
      10,
      1,
      async (i) => {
        seen.push(i);
        if (i === 2) stop = true;
      },
      () => stop,
    );
    // Séquentiel : 0,1,2 traités puis arrêt avant le 3.
    expect(seen).toEqual([0, 1, 2]);
  });
});

describe("resumableBatches", () => {
  const row = { Path: "a/b.pdf", TargetFolder: "1_X", NewTitle: "T" };
  const done = (n: number): ClassementBatch => ({
    itemCount: n,
    rows: [row],
    status: "done",
  });

  it("rien à reprendre sans lot persisté", () => {
    expect(resumableBatches(null, 400)).toBeNull();
    expect(resumableBatches([], 400)).toBeNull();
  });

  it("rien à reprendre quand tous les lots ont abouti", () => {
    expect(resumableBatches([done(400), done(120)], 400)).toBeNull();
  });

  it("projet antérieur (sans statut) lu comme abouti — pas de reprise", () => {
    const legacy = [{ itemCount: 400, rows: [row] }, { itemCount: 12, rows: [row] }];
    expect(resumableBatches(legacy, 400)).toBeNull();
  });

  it("reprend un run interrompu et rend les lots inachevés relançables", () => {
    const resumed = resumableBatches(
      [done(400), { itemCount: 400, rows: [], status: "error", error: "429" }, { itemCount: 30, rows: [] }],
      400,
    );
    expect(resumed).not.toBeNull();
    expect(resumed!.map((b) => b.status)).toEqual(["done", "error", "error"]);
    // L'erreur d'origine est conservée ; un lot jamais lancé reçoit un libellé.
    expect(resumed![1].error).toBe("429");
    expect(resumed![2].error).toBe(BATCH_INTERRUPTED);
    // Le lot abouti garde ses lignes : c'est tout l'intérêt de la reprise.
    expect(resumed![0].rows).toHaveLength(1);
  });

  it("lot marqué abouti mais sans ligne → à relancer", () => {
    const resumed = resumableBatches(
      [{ itemCount: 400, rows: [], status: "done" }, done(30)],
      400,
    );
    expect(resumed!.map((b) => b.status)).toEqual(["error", "done"]);
  });

  it("refuse la reprise si la taille de lot a changé depuis", () => {
    // Les tranches seraient redécoupées autrement : l'index ne désigne plus les
    // mêmes items côté moteur.
    const persisted: ClassementBatch[] = [done(400), { itemCount: 400, rows: [], status: "error" }];
    expect(resumableBatches(persisted, 200)).toBeNull();
    expect(resumableBatches(persisted, 400)).not.toBeNull();
  });
});

describe("resumeStillValid", () => {
  it("vrai quand le corpus re-dérivé fait le même total", () => {
    expect(resumeStillValid([{ itemCount: 400 }, { itemCount: 30 }], 430)).toBe(true);
  });

  it("faux si le corpus a changé (options de préparation, fichier)", () => {
    expect(resumeStillValid([{ itemCount: 400 }, { itemCount: 30 }], 512)).toBe(false);
  });
});
