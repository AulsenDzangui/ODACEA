import { describe, it, expect } from "vitest";
import {
  parsePlanModel,
  serializePlanTreeText,
  serializePlanBlock,
  applyPlanModel,
  addFolderToPlan,
  renameFolderInPlan,
  deleteFolderFromPlan,
  moveNodeInModel,
  slugify,
  validatePlanModel,
  validatePlanText,
  type PlanModel,
} from "@/lib/csv/plan-edit";
import {
  parsePlanTree,
  parsePlanTitles,
  parsePlanRootTitle,
} from "@/lib/csv/plan-tree";

// Plan conforme au gabarit AUD-001 (balises PLAN_STRUCTURE, racine placeholder),
// même matière que les golden files backend.
const PLAN_GABARIT = `### Plan retenu — Fonctionnel

<!-- PLAN_STRUCTURE_START -->
**Arborescence technique** *(chaque dossier porte son titre descriptif puis son nom technique, séparés par « → » ; dossiers uniquement, jamais de fichiers individuels)* **:**

\`\`\`text
Fonds — Affaires scolaires (Commune de Démoville, 2019–2023) → Dossier_racine/
  │
  ├── 1. Inscriptions scolaires → 1_Inscriptions/
  │
  ├── 2. Restauration scolaire → 2_Cantine/
  │     ├── 2.1. Menus → 2-1_Menus/
  │     └── 2.2. Factures → 2-2_Factures/
  │
  └── 3. Vie scolaire → 3_Vie_scolaire/
\`\`\`
<!-- PLAN_STRUCTURE_END -->

**Approche retenue :** Fonctionnelle — les activités structurent le fonds.
**Avantages :** lisible ; extensible.
**Inconvénients :** niveau générique.`;

describe("parsePlanModel", () => {
  it("construit le modèle ordonné avec titres et slugs", () => {
    const model = parsePlanModel(PLAN_GABARIT)!;
    expect(model.rootSlug).toBe("Dossier_racine");
    expect(model.rootTitle).toContain("Affaires scolaires");
    expect(model.nodes.map((n) => n.slug)).toEqual([
      "Inscriptions",
      "Cantine",
      "Vie_scolaire",
    ]);
    expect(model.nodes[1].title).toBe("Restauration scolaire");
    expect(model.nodes[1].children.map((n) => n.slug)).toEqual([
      "Menus",
      "Factures",
    ]);
  });

  it("reconnaît une racine organisationnelle réelle", () => {
    const plan = PLAN_GABARIT.replace("Dossier_racine/", "AFFAIRES_SCOLAIRES/");
    const model = parsePlanModel(plan)!;
    expect(model.rootSlug).toBe("AFFAIRES_SCOLAIRES");
    expect(model.nodes).toHaveLength(3);
  });

  it("retourne null sans arborescence lisible", () => {
    expect(parsePlanModel("Du texte sans arbre.")).toBeNull();
    expect(parsePlanModel("")).toBeNull();
  });

  it("n'accumule pas le label « Fonds — » au fil des aller-retours", () => {
    // Le titre du modèle est nu (le label est ré-ajouté à la sérialisation).
    const model = parsePlanModel(PLAN_GABARIT)!;
    expect(model.rootTitle).toBe(
      "Affaires scolaires (Commune de Démoville, 2019–2023)",
    );
    expect(model.rootTitle).not.toMatch(/Fonds\s*[—–]/);

    // Plusieurs cycles édition→sérialisation→relecture : un seul « Fonds — ».
    let plan: string = PLAN_GABARIT;
    for (let i = 0; i < 3; i++) {
      plan = applyPlanModel(plan, parsePlanModel(plan)!);
    }
    expect((plan.match(/Fonds\s*[—–]/g) ?? []).length).toBe(1);
    expect(parsePlanModel(plan)!.rootTitle).toBe(
      "Affaires scolaires (Commune de Démoville, 2019–2023)",
    );
  });

  it("soigne un plan déjà corrompu (Fonds — répété) à la lecture", () => {
    const corrompu = PLAN_GABARIT.replace(
      "Fonds — Affaires scolaires",
      "Fonds — Fonds — Fonds — Affaires scolaires",
    );
    expect(parsePlanRootTitle(corrompu)).toBe(
      "Affaires scolaires (Commune de Démoville, 2019–2023)",
    );
    // Après réédition, le texte ne porte plus qu'un seul label.
    const next = applyPlanModel(corrompu, parsePlanModel(corrompu)!);
    expect((next.match(/Fonds\s*[—–]/g) ?? []).length).toBe(1);
  });
});

describe("serializePlanTreeText", () => {
  it("recalcule les préfixes numériques depuis la position", () => {
    const model: PlanModel = {
      rootTitle: "Fonds test",
      rootSlug: "Dossier_racine",
      nodes: [
        {
          title: "Bravo",
          slug: "Bravo",
          children: [{ title: "Bravo fils", slug: "Bravo_fils", children: [] }],
        },
        { title: "Alpha", slug: "Alpha", children: [] },
      ],
    };
    const text = serializePlanTreeText(model);
    expect(text).toContain("1. Bravo → 1_Bravo/");
    expect(text).toContain("1.1. Bravo fils → 1-1_Bravo_fils/");
    expect(text).toContain("2. Alpha → 2_Alpha/");
  });

  it("neutralise les flèches dans les titres", () => {
    const model: PlanModel = {
      rootTitle: "Fonds",
      rootSlug: "Dossier_racine",
      nodes: [{ title: "Avant → Après", slug: "Avant_Apres", children: [] }],
    };
    expect(serializePlanTreeText(model)).toContain(
      "1. Avant - Après → 1_Avant_Apres/",
    );
  });
});

describe("round-trip sérialisation ↔ parsing miroir", () => {
  it("le bloc régénéré redonne le même arbre via parsePlanTree", () => {
    const model = parsePlanModel(PLAN_GABARIT)!;
    const block = serializePlanBlock(model);
    expect(parsePlanTree(block)).toEqual(parsePlanTree(PLAN_GABARIT));
    expect(parsePlanTitles(block)).toEqual(parsePlanTitles(PLAN_GABARIT));
  });

  it("un déplacement renumérote et reste parsable", () => {
    const model = parsePlanModel(PLAN_GABARIT)!;
    // « Vie scolaire » passe en tête → tout est renuméroté.
    model.nodes.unshift(model.nodes.pop()!);
    const tree = parsePlanTree(serializePlanBlock(model));
    expect(tree).toEqual({
      "1_Vie_scolaire": null,
      "2_Inscriptions": null,
      "3_Cantine": null,
      "3-1_Menus": "3_Cantine",
      "3-2_Factures": "3_Cantine",
    });
  });
});

describe("moveNodeInModel (glisser-déposer D1)", () => {
  // Ordre du modèle de PLAN_GABARIT : [Inscriptions(0), Cantine(1)[Menus(1,0),
  // Factures(1,1)], Vie_scolaire(2)]. On vérifie le round-trip via le bloc
  // sérialisé re-parsé par parsePlanTree (préfixes recalculés depuis la position).
  const base = () => parsePlanModel(PLAN_GABARIT)!;

  it("déplace un dossier de 1er niveau en sous-dossier d'un autre (inside)", () => {
    const next = moveNodeInModel(base(), [2], [0], "inside")!;
    expect(next).not.toBeNull();
    expect(parsePlanTree(serializePlanBlock(next))).toEqual({
      "1_Inscriptions": null,
      "1-1_Vie_scolaire": "1_Inscriptions",
      "2_Cantine": null,
      "2-1_Menus": "2_Cantine",
      "2-2_Factures": "2_Cantine",
    });
  });

  it("réordonne deux frères (before)", () => {
    const next = moveNodeInModel(base(), [2], [0], "before")!;
    expect(next.nodes.map((n) => n.slug)).toEqual([
      "Vie_scolaire",
      "Inscriptions",
      "Cantine",
    ]);
    expect(parsePlanTree(serializePlanBlock(next))).toMatchObject({
      "1_Vie_scolaire": null,
      "2_Inscriptions": null,
      "3_Cantine": null,
    });
  });

  it("promeut un enfant au premier niveau (after d'un nœud racine)", () => {
    // Menus (1,0) déposé après Cantine (1) → devient dossier de 1er niveau.
    const next = moveNodeInModel(base(), [1, 0], [1], "after")!;
    expect(next.nodes.map((n) => n.slug)).toEqual([
      "Inscriptions",
      "Cantine",
      "Menus",
      "Vie_scolaire",
    ]);
    expect(parsePlanTree(serializePlanBlock(next))).toMatchObject({
      "3_Menus": null,
      "2-1_Factures": "2_Cantine",
    });
  });

  it("refuse de déposer un dossier dans son propre sous-arbre (null)", () => {
    // Cantine (1) déposé dans son enfant Menus (1,0).
    expect(moveNodeInModel(base(), [1], [1, 0], "inside")).toBeNull();
  });

  it("refuse un dépôt sur soi-même et n'altère pas l'entrée", () => {
    const model = base();
    const snapshot = structuredClone(model);
    expect(moveNodeInModel(model, [1], [1], "after")).toBeNull();
    expect(model).toEqual(snapshot); // pas de mutation de l'entrée
  });
});

describe("applyPlanModel", () => {
  it("remplace entre les balises PLAN_STRUCTURE sans toucher au reste", () => {
    const model = parsePlanModel(PLAN_GABARIT)!;
    model.nodes[0].title = "Inscriptions et effectifs";
    model.nodes[0].slug = "Inscriptions_effectifs";
    const next = applyPlanModel(PLAN_GABARIT, model);
    expect(next).toContain("### Plan retenu — Fonctionnel");
    expect(next).toContain("**Approche retenue :** Fonctionnelle");
    expect(next).toContain("<!-- PLAN_STRUCTURE_START -->");
    expect(next).toContain(
      "1. Inscriptions et effectifs → 1_Inscriptions_effectifs/",
    );
    expect(next).not.toContain("1_Inscriptions/");
    // Toujours rééditable : le nouveau texte se re-parse à l'identique.
    expect(parsePlanModel(next)!.nodes[0].slug).toBe("Inscriptions_effectifs");
  });

  it("repli en-tête + fence quand les balises manquent", () => {
    const sansBalises = PLAN_GABARIT.replace(
      /<!--\s*PLAN_STRUCTURE_(START|END)\s*-->\n?/g,
      "",
    );
    const model = parsePlanModel(sansBalises)!;
    model.nodes.pop();
    const next = applyPlanModel(sansBalises, model);
    expect(next).toContain("**Approche retenue :**");
    expect(next).not.toContain("Vie_scolaire");
    expect(Object.keys(parsePlanTree(next))).toHaveLength(4);
  });

  it("repli plage de lignes pour un plan collé sans en-tête ni fence", () => {
    const brut = [
      "Mon plan maison",
      "",
      "1. Courrier → 1_Courrier/",
      "2. Budget → 2_Budget/",
      "",
      "Remarque finale.",
    ].join("\n");
    const model = parsePlanModel(brut)!;
    model.nodes.push({ title: "Divers", slug: "Divers", children: [] });
    const next = applyPlanModel(brut, model);
    expect(next).toContain("Mon plan maison");
    expect(next).toContain("Remarque finale.");
    expect(parsePlanTree(next)).toEqual({
      "1_Courrier": null,
      "2_Budget": null,
      "3_Divers": null,
    });
  });
});

describe("validatePlanModel", () => {
  it("plan conforme : aucun problème", () => {
    expect(validatePlanModel(parsePlanModel(PLAN_GABARIT)!)).toEqual([]);
  });

  it("signale caractères interdits, doublons et titres vides", () => {
    const model: PlanModel = {
      rootTitle: "Fonds",
      rootSlug: "Dossier_racine",
      nodes: [
        { title: "", slug: "Comptabilité", children: [] },
        { title: "Budget", slug: "Budget 2024", children: [] },
        { title: "Encore", slug: "budget 2024", children: [] },
      ],
    };
    const messages = validatePlanModel(model).map((i) => i.message);
    expect(messages.some((m) => m.includes("titre descriptif vide"))).toBe(true);
    expect(messages.filter((m) => m.includes("caractères invalides"))).toHaveLength(3);
    expect(messages.some((m) => m.includes("doublon de nom"))).toBe(true);
  });

  it("signale une racine non reconnaissable", () => {
    const model: PlanModel = {
      rootTitle: "Fonds",
      rootSlug: "Racine",
      nodes: [{ title: "A", slug: "A_voir", children: [] }],
    };
    const issues = validatePlanModel(model);
    expect(issues.some((i) => i.tech === "" && i.message.includes("« _ »"))).toBe(
      true,
    );
  });

  it("signale un plan sans dossier", () => {
    const model: PlanModel = {
      rootTitle: "Fonds",
      rootSlug: "Dossier_racine",
      nodes: [],
    };
    expect(
      validatePlanModel(model).some((i) => i.message.includes("aucun dossier")),
    ).toBe(true);
  });
});

describe("validatePlanText", () => {
  it("plan conforme : aucun problème", () => {
    expect(validatePlanText(PLAN_GABARIT)).toEqual([]);
  });

  it("signale l'arborescence introuvable", () => {
    expect(validatePlanText("Pas d'arbre ici.")[0]).toContain("introuvable");
  });

  it("signale doublons et préfixes incohérents", () => {
    const plan = [
      "1. Courrier → 1_Courrier/",
      "1. Courrier bis → 1_Courrier/",
      "2.1. Orphelin → 2-1_Orphelin/",
    ].join("\n");
    const issues = validatePlanText(plan);
    expect(issues.some((m) => m.includes("Doublon") && m.includes("1_Courrier"))).toBe(true);
    expect(
      issues.some((m) => m.includes("Préfixe incohérent") && m.includes("2-1_Orphelin")),
    ).toBe(true);
  });

  it("signale un nom technique accentué (miroir TS non concordant)", () => {
    const plan = "1. Comptabilité → 1_Comptabilité/";
    // Le miroir JS (\\w ASCII) ne lit pas ce nom : il doit être signalé comme
    // introuvable ou invalide, jamais accepté en silence.
    const issues = validatePlanText(plan);
    expect(issues.length).toBeGreaterThan(0);
  });
});

describe("slugify", () => {
  it("retire accents et caractères interdits", () => {
    expect(slugify("Comptabilité & paie (2019)")).toBe("Comptabilite_paie_2019");
    expect(slugify("  ")).toBe("Nouveau_dossier");
  });
});

describe("addFolderToPlan (rattrapage)", () => {
  it("ajoute un sous-dossier sous le parent désigné et renvoie son nom technique", () => {
    const res = addFolderToPlan(PLAN_GABARIT, "2_Cantine", "Plannings");
    expect(res).not.toBeNull();
    // Troisième enfant de « 2_Cantine » → préfixe recalculé 2-3.
    expect(res!.tech).toBe("2-3_Plannings");
    const tree = parsePlanTree(res!.plan);
    expect(tree["2-3_Plannings"]).toBe("2_Cantine");
    // Le dossier devient une cible reconnue du plan (plus « hors plan »).
    expect(Object.keys(tree)).toContain("2-3_Plannings");
  });

  it("ajoute un dossier de premier niveau quand le parent est null", () => {
    const res = addFolderToPlan(PLAN_GABARIT, null, "Archives diverses");
    expect(res).not.toBeNull();
    // Quatrième dossier de premier niveau → préfixe 4.
    expect(res!.tech).toBe("4_Archives_diverses");
    expect(parsePlanTree(res!.plan)["4_Archives_diverses"]).toBeNull();
  });

  it("le titre descriptif saisi est conservé dans le plan régénéré", () => {
    const res = addFolderToPlan(PLAN_GABARIT, "2_Cantine", "Plannings de service")!;
    expect(parsePlanTitles(res.plan)["2-3_Plannings_de_service"]).toBe(
      "Plannings de service",
    );
  });

  it("renvoie null sur un parent introuvable", () => {
    expect(addFolderToPlan(PLAN_GABARIT, "9_Inexistant", "X")).toBeNull();
  });

  it("renvoie null quand l'arborescence est illisible", () => {
    expect(addFolderToPlan("Pas de plan ici.", null, "X")).toBeNull();
  });
});

describe("renameFolderInPlan", () => {
  it("renomme un dossier et renvoie le remap ancien → nouveau nom technique", () => {
    const res = renameFolderInPlan(PLAN_GABARIT, "2-1_Menus", "Cartes de menus")!;
    // Position inchangée → préfixe 2-1 conservé, seul le slug change.
    expect(res.tech).toBe("2-1_Cartes_de_menus");
    expect(res.remap.get("2-1_Menus")).toBe("2-1_Cartes_de_menus");
    const tree = parsePlanTree(res.plan);
    expect(tree["2-1_Cartes_de_menus"]).toBe("2_Cantine");
    expect(tree["2-1_Menus"]).toBeUndefined();
    // Les frères ne bougent pas.
    expect(tree["2-2_Factures"]).toBe("2_Cantine");
  });

  it("renvoie null sur un dossier introuvable", () => {
    expect(renameFolderInPlan(PLAN_GABARIT, "9_X", "Y")).toBeNull();
  });
});

describe("deleteFolderFromPlan", () => {
  it("supprime un dossier et décale les frères suivants (remap)", () => {
    const res = deleteFolderFromPlan(PLAN_GABARIT, "2-1_Menus")!;
    expect(res.removed).toEqual(["2-1_Menus"]);
    // « 2-2_Factures » devient le 1er enfant → 2-1.
    expect(res.remap.get("2-2_Factures")).toBe("2-1_Factures");
    const tree = parsePlanTree(res.plan);
    expect(tree["2-1_Menus"]).toBeUndefined();
    expect(tree["2-1_Factures"]).toBe("2_Cantine");
    expect(tree["2-2_Factures"]).toBeUndefined();
  });

  it("supprime le sous-arbre entier d'un dossier parent", () => {
    const res = deleteFolderFromPlan(PLAN_GABARIT, "2_Cantine")!;
    // Le parent et ses deux enfants disparaissent.
    expect(new Set(res.removed)).toEqual(
      new Set(["2_Cantine", "2-1_Menus", "2-2_Factures"]),
    );
    const tree = parsePlanTree(res.plan);
    expect(Object.keys(tree)).not.toContain("2_Cantine");
    // « 3_Vie_scolaire » remonte en 2e position.
    expect(res.remap.get("3_Vie_scolaire")).toBe("2_Vie_scolaire");
  });

  it("renvoie null sur un dossier introuvable", () => {
    expect(deleteFolderFromPlan(PLAN_GABARIT, "9_X")).toBeNull();
  });
});
