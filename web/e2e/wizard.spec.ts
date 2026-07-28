// E2E Playwright du wizard complet : upload → audit → classement →
// téléchargement, contre un backend entièrement mocké via page.route.
// Réutilise les fixtures B5 du backend (CSV + golden files LLM) : le front est
// testé sur exactement la même matière que le moteur Python.
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const FIXTURES = path.resolve(__dirname, "../../backend/tests/fixtures");
const csvText = fs.readFileSync(path.join(FIXTURES, "archifiltre_small.csv"), "utf-8");
const goldenAud = fs.readFileSync(path.join(FIXTURES, "golden/aud_small.md"), "utf-8");

// Mini-parseur du CSV de fixture (QUOTE_ALL, séparateur ;) → lignes objets,
// comme le ferait /parse côté Python.
function parseFixtureCsv(text: string): Record<string, string>[] {
  // Découpage tolérant au CRLF : les fixtures sont partagées avec le backend et
  // Git les restitue en CRLF sous Windows. Découper sur "\n" seul laissait un
  // "\r" collé à la dernière cellule — donc une colonne `Content.EndDate\r`, et
  // un front qui croyait le CSV non conforme au format SEDA.
  const lines = text.trim().split(/\r?\n/);
  const cells = (line: string) =>
    line.split(";").map((c) => c.replace(/^"|"$/g, "").replace(/""/g, '"'));
  const header = cells(lines[0]);
  return lines.slice(1).map((line) => {
    const values = cells(line);
    return Object.fromEntries(header.map((h, i) => [h, values[i] ?? ""]));
  });
}

const rows = parseFixtureCsv(csvText);
const columns = Object.keys(rows[0]);

const llmRows = [
  { Path: "inscriptions/liste_eleves_2022.xlsx", TargetFolder: "1_Inscriptions", NewTitle: "2022-09-01_liste-eleves_VF.xlsx" },
  { Path: "inscriptions/liste eleves 2023 v2.xlsx", TargetFolder: "1_Inscriptions", NewTitle: "2023-09-04_liste-eleves_V02.xlsx" },
  { Path: "cantine/menus_janvier.docx", TargetFolder: "2-1_Menus", NewTitle: "2022-01-03_menus-janvier_VF.docx" },
  { Path: "cantine/facture_traiteur_2021.pdf", TargetFolder: "2-2_Factures", NewTitle: "2021-11-15_facture-traiteur_VF.pdf" },
  { Path: "divers/photo_kermesse_001.jpg", TargetFolder: "3_Vie_scolaire", NewTitle: "2022-06-25_photo-kermesse-001_VF.jpg" },
  { Path: "divers/note service.doc", TargetFolder: "3_Vie_scolaire", NewTitle: "2019-01-10_note-service_VF.doc" },
];

function sse(events: object[]): string {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
}

// Corps de la dernière requête POST /journal observée — pour vérifier que le
// front transmet le modèle figé *par étape* (carte `models`), pas le réglage courant.
let journalRequestBody: Record<string, unknown> | null = null;

/** Branche tous les mocks /api/py/* nécessaires au parcours nominal. */
async function mockBackend(page: Page) {
  journalRequestBody = null;
  await page.route("**/api/py/health", (route) =>
    route.fulfill({ json: { status: "ok" } }),
  );
  await page.route("**/api/py/models", (route) =>
    route.fulfill({
      json: {
        default: "gpt-test",
        models: ["gpt-test"],
        localEndpoints: {},
        demoMode: false,
      },
    }),
  );
  await page.route("**/api/py/demo/csv", (route) =>
    route.fulfill({ contentType: "text/csv", body: csvText }),
  );
  // Conversion d'un CSV Resip « dossiers seuls » en plan de référence.
  await page.route("**/api/py/reference-plan/from-csv", (route) =>
    route.fulfill({
      json: {
        tree: "```text\nFonds — [Mon fonds] → Mon_fonds/\n  └── Pilotage → Pilotage/\n```",
        validationErrors: [],
        warnings: [],
        folderCount: 1,
        ignoredItemCount: 0,
        rootTitle: "Mon fonds",
      },
    }),
  );
  // Plan fourni par l'archiviste adopté sans appel LLM (POST /plan/from-file).
  await page.route("**/api/py/plan/from-file", (route) =>
    route.fulfill({
      json: {
        plan: "**Arborescence technique** :\n\n```text\nFonds — Mon fonds → Dossier_racine/\n  │\n  └── 1. Inscriptions → 1_Inscriptions/\n```",
        planTree: { "1_Inscriptions": null },
        folderCount: 1,
        ignoredItemCount: 1,
        rootTitle: "Mon fonds",
        warnings: ["1 ligne(s) fichier (Item) ignorée(s)."],
        format: "csv",
      },
    }),
  );
  await page.route("**/api/py/parse", (route) =>
    route.fulfill({
      json: {
        rows,
        columns,
        validationErrors: [],
        stats: { rowCount: 10, itemCount: 6, recordGrpCount: 4 },
        prepared: {
          previewRows: rows.slice(0, 5),
          columns,
          columnCount: columns.length,
          itemCount: 6,
        },
        tokenEstimate: {
          auditTokens: 2000,
          classementTokensPerBatch: 1500,
          classementBatches: 1,
          classementTotalTokens: 1500,
          totalTokens: 3500,
          // Coût € indicatif joint pour un modèle cloud connu.
          costEstimate: {
            label: "GPT-5 mini",
            model: "gpt-5-mini",
            priceDate: "2026-06-14",
            inputEurPerM: 0.23,
            outputEurPerM: 1.84,
            inputEur: 0.000805,
            outputEur: 0,
            totalEur: 0.000805,
          },
          // Recommandation de budget d'entrée AUD-001 (réglage courant ≠
          // recommandé pour ce vrac).
          budgetRecommendation: {
            itemCount: 6,
            tier: "petit",
            currentSampleN: 5,
            currentCleanDates: true,
            recommendedSampleN: 0,
            recommendedCleanDates: true,
            matchesRecommendation: false,
            estimatedAuditTokensAtRecommended: 2300,
            rationale:
              "petit vrac : envoyer tous les fichiers (aucun échantillonnage)",
            tableDate: "2026-06-15",
          },
        },
      },
    }),
  );
  await page.route("**/api/py/audit", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: sse([
        { type: "reasoning", delta: "Analyse du vrac…" },
        { type: "text", delta: goldenAud },
        {
          type: "done",
          report: goldenAud,
          plan: goldenAud.match(
            /<!-- PLAN_STRUCTURE_START -->([\s\S]*?)<!-- PLAN_STRUCTURE_END -->/,
          )![1],
          notes: "Notes pour l'archiviste.",
          planTree: {
            AFFAIRES_SCOLAIRES: null,
            "1_Inscriptions": "AFFAIRES_SCOLAIRES",
            "2_Cantine": "AFFAIRES_SCOLAIRES",
            "2-1_Menus": "2_Cantine",
            "2-2_Factures": "2_Cantine",
            "3_Vie_scolaire": "AFFAIRES_SCOLAIRES",
          },
          usage: { input_tokens: 1000, output_tokens: 500, total_tokens: 1500 },
          durationMs: 1234,
          model: "gpt-test",
        },
      ]),
    }),
  );
  await page.route("**/api/py/classement/prepare", (route) =>
    route.fulfill({
      json: { items: [], total: 6, columns: ["Ref", "Path", "CurrentTitle", "Date"] },
    }),
  );
  await page.route("**/api/py/classement/batch", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: sse([
        { type: "text", delta: "```csv\nPath;TargetFolder;NewTitle\n…\n```" },
        { type: "progress", batch: 0, totalBatches: 0, itemsDone: 6 },
        {
          type: "done",
          llmRows,
          rawText: "réponse brute",
          usage: { input_tokens: 800, output_tokens: 300, total_tokens: 1100 },
          durationMs: 2345,
          model: "gpt-test",
        },
      ]),
    }),
  );
  await page.route("**/api/py/classement/finalize", (route) =>
    route.fulfill({
      json: {
        resip: {
          rows,
          columns,
          warnings: [],
          // Anomalies typées catégorisées côté moteur — le front les
          // présente telles quelles (ici aucune : parcours nominal).
          anomalies: [],
          stats: {
            planParsed: true,
            planFolders: 6,
            outputFolders: 6,
            foldersOffPlan: [],
            foldersMissing: [],
            itemsMalformed: 0,
            planMatches: true,
            itemsTotal: 6,
            itemsClassified: 6,
            itemsUnclassified: 0,
            extensionsFixed: 0,
            targetsUnknown: 0,
            pathsNotFound: 0,
            refsUnresolved: 0,
          },
        },
      },
    }),
  );

  // Journal de traitement : rendu côté moteur, le front ne fait que
  // télécharger le Markdown renvoyé. On capture le corps de la requête pour
  // vérifier que le modèle figé *par étape* (et non le réglage courant) part bien.
  await page.route("**/api/py/journal", (route) => {
    journalRequestBody = route.request().postDataJSON();
    return route.fulfill({
      json: {
        markdown: "# Journal de traitement ODACEA\n\n## Traitement\n",
        journal: { tool: "ODACEA", journalVersion: "1" },
      },
    });
  });

  // Arborescence modèle : rendu côté moteur (POST /manifest), le front
  // renvoie les lignes RESIP et télécharge le Markdown produit.
  await page.route("**/api/py/manifest", (route) =>
    route.fulfill({
      json: {
        markdown: "# Arborescence modèle ODACEA\n\n## Répertoires\n",
        manifest: { tool: "ODACEA", manifestVersion: "1" },
      },
    }),
  );

  // Comparaison multi-plans : le moteur compare les plans renvoyés par le
  // front (textes obtenus par N audits) → variantes + croisement des dossiers.
  await page.route("**/api/py/plan-compare", (route) =>
    route.fulfill({
      json: {
        variants: [
          {
            index: 1,
            planExtracted: true,
            folders: 5,
            depth: 2,
            maxWidth: 3,
            leaves: 3,
            folderLabels: ["cantine", "inscriptions", "menus"],
            uniqueFolders: ["inscriptions"],
          },
          {
            index: 2,
            planExtracted: true,
            folders: 4,
            depth: 2,
            maxWidth: 2,
            leaves: 2,
            folderLabels: ["cantine", "menus"],
            uniqueFolders: ["vie scolaire"],
          },
        ],
        comparison: {
          variantCount: 2,
          commonFolders: ["cantine", "menus"],
          commonFolderCount: 2,
          allFolders: ["cantine", "inscriptions", "menus", "vie scolaire"],
          identical: false,
          folderCountRange: { min: 4, max: 5 },
          depthRange: { min: 2, max: 2 },
          leavesRange: { min: 2, max: 3 },
        },
        markdown: "Variante …",
      },
    }),
  );

  // Enrichissement local : le moteur lit les binaires locaux et renvoie le
  // CSV enrichi (texte) + rapports déterministes. Le front le réinjecte via /parse.
  await page.route("**/api/py/enrich", (route) =>
    route.fulfill({
      json: {
        enrichedCsv: csvText,
        contentAccessNotice: "Lecture locale du contenu des fichiers…",
        report: {
          totalItems: 6,
          enriched: 4,
          alreadyFilled: 1,
          noText: 1,
          unsupported: 0,
          missing: 0,
          errors: 0,
        },
        fingerprint: {
          totalItems: 6,
          hashed: 6,
          alreadyHashed: 0,
          missing: 0,
          skipped: 0,
          errors: 0,
        },
        duplicates: { groups: 1, files: 2, redundant: 1, examples: [] },
      },
    }),
  );
}

test("wizard complet : upload → audit → classement → téléchargement", async ({ page }) => {
  await mockBackend(page);
  await page.goto("/");

  // ── Étape 1 : upload ──────────────────────────────────────────────────────
  await page.setInputFiles('main input[type="file"]', {
    name: "vrac.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csvText, "utf-8"),
  });
  // Stats et estimation issues de /parse affichées.
  await expect(page.getByText("Continuer vers l'audit")).toBeVisible();
  // Le coût € indicatif du modèle cloud est rendu sous l'estimation tokens.
  await expect(page.getByText("Coût d'entrée estimé")).toBeVisible();
  await expect(page.getByText(/GPT-5 mini/)).toBeVisible();
  await expect(page.getByText(/< 0,01 €/)).toBeVisible();
  // La recommandation de budget d'entrée AUD-001 est rendue (réglage courant
  // « 5/dossier » vs recommandé « tous » pour ce vrac).
  await expect(page.getByText("Profondeur d'entrée AUD-001")).toBeVisible();
  await expect(page.getByText(/5\/dossier → tous/)).toBeVisible();
  await page.getByText("Continuer vers l'audit").click();

  // ── Étape 2 : audit ───────────────────────────────────────────────────────
  // On importe un CSV Resip « dossiers seuls » (converti en arborescence par
  // /reference-plan/from-csv) + le mode « conform », et on vérifie que le bloc et
  // le mode partent bien dans le corps de /audit (le front ne fait que
  // transporter — l'injection est côté moteur).
  await page
    .locator('[data-testid="reference-plan-dropzone"] input[type="file"]')
    .setInputFiles({
      name: "dossiers.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(
        "ID;ParentID;File;Content.DescriptionLevel;Content.Title;Content.StartDate;Content.EndDate\n" +
          "1;;.;RecordGrp;Mon fonds;;\n",
      ),
    });
  // Une fois le référentiel chargé, le sélecteur de mode apparaît.
  await page.getByLabel("Façon d'utiliser ce référentiel").click();
  await page.getByRole("option", { name: "S'y conformer (prescriptif)" }).click();

  const auditRequest = page.waitForRequest(
    (req) => req.url().includes("/api/py/audit") && req.method() === "POST",
  );
  await page.getByRole("button", { name: "Lancer l'audit" }).click();
  const auditBody = JSON.parse((await auditRequest).postData() ?? "{}");
  expect(auditBody.referencePlan).toContain("Mon_fonds/");
  expect(auditBody.referenceMode).toBe("conform");
  // Le plan extrait du golden AUD-001 est rendu (arborescence visible).
  await expect(page.getByText("Continuer vers le classement")).toBeEnabled();
  // Fin d'audit = création auto du projet : router.replace("/?p=…") déclenche
  // l'effet de restauration du snapshot (étape audit). On attend que cette
  // séquence soit terminée avant de naviguer, sinon elle annule le passage à
  // l'étape classement.
  await page.waitForURL(/\?p=/);
  await page.waitForTimeout(300);
  await page.getByText("Continuer vers le classement").click();

  // ── Étape 3 : classement ──────────────────────────────────────────────────
  await page.getByRole("button", { name: "Lancer le classement" }).click();
  // Conversion finalisée : le CSV final est téléchargeable.
  const downloadButton = page.getByRole("button", { name: /Télécharger le CSV final/ });
  await expect(downloadButton).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await downloadButton.click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^classement_final_.*\.csv$/);

  // Traçabilité : le modèle figé de l'étape est affiché à l'écran (par étape).
  await expect(page.getByText(/modèle : gpt-test/).first()).toBeVisible();

  // Les exports secondaires sont regroupés sous le menu « Exporter » (allègement
  // du pied) ; chaque sélection ferme le menu, d'où sa réouverture entre deux.

  // Le journal de traitement (POST /journal) est téléchargeable en Markdown.
  await page.getByRole("button", { name: /Exporter/ }).click();
  const journalDownloadPromise = page.waitForEvent("download");
  await page
    .getByRole("menuitem", { name: /Journal de traitement/ })
    .click();
  const journalDownload = await journalDownloadPromise;
  expect(journalDownload.suggestedFilename()).toMatch(
    /^journal_traitement_.*\.md$/,
  );
  // Traçabilité : le journal transporte le modèle figé *par étape* (capturé des
  // done{} SSE), via la carte `models` — pas le seul réglage courant.
  expect(journalRequestBody?.models).toMatchObject({
    "AUD-001": "gpt-test",
    "CLA-001": "gpt-test",
  });

  // L'arborescence modèle (POST /manifest) est téléchargeable en Markdown.
  await page.getByRole("button", { name: /Exporter/ }).click();
  const manifestDownloadPromise = page.waitForEvent("download");
  await page
    .getByRole("menuitem", { name: /Arborescence modèle/ })
    .click();
  const manifestDownload = await manifestDownloadPromise;
  expect(manifestDownload.suggestedFilename()).toMatch(
    /^arborescence_modele_.*\.md$/,
  );
});

test("Audit comparatif multi-plans : N audits, comparaison, choix", async ({
  page,
}) => {
  await mockBackend(page);

  // Compte les audits réellement lancés (un par variante demandée).
  let auditCalls = 0;
  page.on("request", (req) => {
    if (req.url().includes("/api/py/audit") && req.method() === "POST") {
      auditCalls += 1;
    }
  });

  await page.goto("/");
  await page.setInputFiles('main input[type="file"]', {
    name: "vrac.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csvText, "utf-8"),
  });
  await expect(page.getByText("Continuer vers l'audit")).toBeVisible();
  await page.getByText("Continuer vers l'audit").click();

  // Demander 2 propositions à comparer.
  await page.getByLabel("Propositions de plan à comparer").click();
  await page.getByRole("option", { name: "2 propositions à comparer" }).click();

  const compareRequest = page.waitForRequest(
    (req) =>
      req.url().includes("/api/py/plan-compare") && req.method() === "POST",
  );
  await page.getByRole("button", { name: "Comparer 2 propositions" }).click();

  // Le front a bien renvoyé les plans collectés au moteur (transport pur).
  const compareBody = JSON.parse((await compareRequest).postData() ?? "{}");
  expect(Array.isArray(compareBody.plans)).toBe(true);
  expect(compareBody.plans).toHaveLength(2);

  // La vue de comparaison rendue par le moteur s'affiche.
  await expect(
    page.getByText("Comparaison de 2 propositions de plan"),
  ).toBeVisible();
  await expect(page.getByText("Proposition #1")).toBeVisible();
  await expect(page.getByText("Proposition #2")).toBeVisible();
  // Dossiers communs et propres présentés (calcul moteur).
  await expect(
    page.getByText("Dossiers communs à toutes les propositions (2)"),
  ).toBeVisible();

  // Deux audits ont été lancés.
  expect(auditCalls).toBe(2);

  // Adopter la première proposition → on bascule sur le résultat d'audit normal.
  await page
    .getByRole("button", { name: "Choisir cette proposition" })
    .first()
    .click();
  await expect(page.getByText("Continuer vers le classement")).toBeEnabled();
});

test("Enrichissement local : le vrac enrichi est réinjecté via /parse", async ({
  page,
}) => {
  await mockBackend(page);
  await page.goto("/");

  await page.setInputFiles('main input[type="file"]', {
    name: "vrac.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csvText, "utf-8"),
  });
  await expect(page.getByText("Continuer vers l'audit")).toBeVisible();

  // Ouvre le panneau d'enrichissement (étape 0, backend local) et lance-le.
  await page.getByRole("button", { name: /Enrichissement local/ }).click();
  await page
    .getByLabel("Racine locale du vrac")
    .fill("/home/archiviste/vrac_scolarite");

  const enrichRequest = page.waitForRequest(
    (req) => req.url().includes("/api/py/enrich") && req.method() === "POST",
  );
  await page.getByRole("button", { name: /Enrichir le vrac/ }).click();

  // La racine locale part bien dans le corps (le front ne fait que transporter).
  const enrichBody = JSON.parse((await enrichRequest).postData() ?? "{}");
  expect(enrichBody.sourceRoot).toBe("/home/archiviste/vrac_scolarite");

  // Rapport rendu par le moteur affiché ; on peut poursuivre vers l'audit.
  await expect(page.getByText("Vrac enrichi")).toBeVisible();
  await expect(page.getByText(/4 description\(s\) ajoutée\(s\)/)).toBeVisible();
  await expect(page.getByText("Continuer vers l'audit")).toBeVisible();
});

test("Plan fourni adopté sans audit LLM : import → plan → classement", async ({
  page,
}) => {
  await mockBackend(page);

  // Aucun /audit ne doit être appelé sur ce parcours (bypass de l'audit).
  let auditCalls = 0;
  page.on("request", (req) => {
    if (req.url().includes("/api/py/audit") && req.method() === "POST") {
      auditCalls += 1;
    }
  });

  await page.goto("/");
  await page.setInputFiles('main input[type="file"]', {
    name: "vrac.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csvText, "utf-8"),
  });
  await expect(page.getByText("Continuer vers l'audit")).toBeVisible();
  await page.getByText("Continuer vers l'audit").click();

  // Déposer un plan « dossiers seuls » dans la zone d'adoption dédiée.
  const planFromFileRequest = page.waitForRequest(
    (req) =>
      req.url().includes("/api/py/plan/from-file") && req.method() === "POST",
  );
  await page
    .locator('[data-testid="import-plan-dropzone"] input[type="file"]')
    .setInputFiles({
      name: "mon_plan.csv",
      mimeType: "text/csv",
      buffer: Buffer.from(
        "ID;ParentID;File;Content.DescriptionLevel;Content.Title;Content.StartDate;Content.EndDate\n" +
          "1;;.;RecordGrp;Mon fonds;;\n" +
          "2;1;Fonds/Inscriptions;RecordGrp;Inscriptions;;\n",
      ),
    });
  // Le front ne fait que transporter le texte.
  const body = JSON.parse((await planFromFileRequest).postData() ?? "{}");
  expect(body.name).toBe("mon_plan.csv");
  expect(body.content).toContain("RecordGrp");

  // Plan adopté : la vue des résultats apparaît (origine « fourni », sans audit).
  // Dès qu'un plan existe, l'onglet actif par défaut est « Plan de classement » ;
  // le bandeau d'origine, lui, vit dans l'onglet « Rapport d'audit ».
  await page.getByRole("tab", { name: "Rapport d'audit" }).click();
  await expect(
    page.getByText("Plan fourni par l'archiviste"),
  ).toBeVisible();
  await expect(page.getByText("Continuer vers le classement")).toBeEnabled();
  expect(auditCalls).toBe(0);

  // On peut poursuivre le parcours normal jusqu'au classement.
  await page.waitForURL(/\?p=/);
  await page.waitForTimeout(300);
  await page.getByText("Continuer vers le classement").click();
  await page.getByRole("button", { name: "Lancer le classement" }).click();
  await expect(
    page.getByRole("button", { name: /Télécharger le CSV final/ }),
  ).toBeVisible();

  // Le journal consigne l'origine « plan fourni ».
  await page.getByRole("button", { name: /Exporter/ }).click();
  const journalDownloadPromise = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: /Journal de traitement/ }).click();
  await journalDownloadPromise;
  expect(journalRequestBody?.planOrigin).toBe("fourni");
  expect(journalRequestBody?.command).toBe("classement");
});

test("erreur LLM à l'audit : message et hint affichés sans console", async ({ page }) => {
  await mockBackend(page);
  await page.route("**/api/py/audit", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: sse([
        {
          type: "error",
          message: "Clé API invalide ou manquante pour ce modèle.",
          code: "llm_auth",
          hint: "Renseignez ou corrigez la clé API dans les réglages (panneau latéral).",
        },
      ]),
    }),
  );
  await page.goto("/");
  await page.setInputFiles('main input[type="file"]', {
    name: "vrac.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csvText, "utf-8"),
  });
  await page.getByText("Continuer vers l'audit").click();
  await page.getByRole("button", { name: "Lancer l'audit" }).click();

  // Taxonomie d'erreurs rendue dans l'alerte : message + action recommandée.
  await expect(page.getByText("Clé API invalide ou manquante pour ce modèle.")).toBeVisible();
  await expect(page.getByText(/corrigez la clé API dans les réglages/)).toBeVisible();
});

// Critères d'acceptation : démo en < 3 clics (D7), plan éditable en
// arbre sans Markdown, re-classement sans appel LLM.
test(" — démo en <3 clics, édition du plan en arbre, reclassement sans LLM", async ({
  page,
}) => {
  await mockBackend(page);

  // Trace des appels LLM, pour prouver que le re-classement n'en déclenche aucun.
  const llmCalls: string[] = [];
  page.on("request", (req) => {
    const u = req.url();
    if (u.includes("/api/py/audit") || u.includes("/api/py/classement/batch"))
      llmCalls.push(u);
  });

  await page.goto("/");

  // ── D7 : auditer la démo en 3 clics depuis l'arrivée ──────────────────────
  await page
    .getByRole("button", { name: /Charger un jeu de démonstration/ })
    .click(); // clic 1
  await expect(page.getByText("Continuer vers l'audit")).toBeVisible();
  await page.getByText("Continuer vers l'audit").click(); // clic 2
  await page.getByRole("button", { name: "Lancer l'audit" }).click(); // clic 3
  await expect(page.getByText("Continuer vers le classement")).toBeEnabled();

  // ── le plan est éditable en arbre (champs de saisie, pas de Markdown) ─
  // L'onglet « Plan de classement » est actif par défaut après l'audit.
  const titre2 = page.getByLabel("Titre du dossier 2", { exact: true });
  await expect(titre2).toHaveValue("Restauration scolaire");
  await titre2.fill("Restauration et cantine");
  await expect(titre2).toHaveValue("Restauration et cantine");

  // ── Aller au classement ───────────────────────────────────────────────────
  // Recentrage : ODACEA ne se réserve que le rattrapage des fichiers que
  // l'IA a laissés non classés (la retouche des items déjà classés relève de
  // Resip). On surcharge donc le classement de CE test pour qu'un item reste
  // non classé : sortie LLM amputée du 6ᵉ item + stats itemsUnclassified: 1.
  const llmRowsPartial = llmRows.slice(0, 5); // « divers/note service.doc » non classé
  // Sortie RESIP correspondante : le 6ᵉ item, non classé, n'apparaît pas dans les
  // lignes finales → 5/6 items classés, « 1 non classé » côté rapport de
  // couverture (c'est le compteur `missing` qui pilote l'affichage du panneau).
  const rowsPartial = rows.filter(
    (r) => r["File"] !== "divers/note service.doc",
  );
  await page.route("**/api/py/classement/batch", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: sse([
        { type: "text", delta: "```csv\nPath;TargetFolder;NewTitle\n…\n```" },
        { type: "progress", batch: 0, totalBatches: 0, itemsDone: 5 },
        {
          type: "done",
          llmRows: llmRowsPartial,
          rawText: "réponse brute",
          usage: { input_tokens: 800, output_tokens: 300, total_tokens: 1100 },
          durationMs: 2345,
          model: "gpt-test",
        },
      ]),
    }),
  );
  await page.route("**/api/py/classement/finalize", (route) =>
    route.fulfill({
      json: {
        resip: {
          rows: rowsPartial,
          columns,
          warnings: [],
          anomalies: [],
          stats: {
            planParsed: true,
            planFolders: 6,
            outputFolders: 6,
            foldersOffPlan: [],
            foldersMissing: [],
            itemsMalformed: 0,
            planMatches: true,
            itemsTotal: 6,
            itemsClassified: 5,
            itemsUnclassified: 1,
            extensionsFixed: 0,
            targetsUnknown: 0,
            pathsNotFound: 0,
            refsUnresolved: 0,
          },
        },
      },
    }),
  );

  await page.waitForURL(/\?p=/);
  await page.waitForTimeout(300);
  await page.getByText("Continuer vers le classement").click();
  await page.getByRole("button", { name: "Lancer le classement" }).click();
  await expect(
    page.getByRole("button", { name: /Télécharger le CSV final/ }),
  ).toBeVisible();

  const llmCallsAfterClassement = llmCalls.length;

  // ── rattacher le fichier non classé et re-finaliser sans rappeler le LLM ─
  await page
    .getByRole("button", { name: /Corriger le classement — 1 non classé/ })
    .click();
  const cible = page.getByLabel("Dossier cible de divers/note service.doc");
  await cible.click();
  await page.getByRole("option", { name: /Vie scolaire/ }).click();

  const finalizePromise = page.waitForResponse("**/api/py/classement/finalize");
  await page
    .getByRole("button", { name: /Appliquer et re-finaliser/ })
    .click();
  await finalizePromise; // re-finalisation = passe Python pure

  // Aucun nouvel appel audit/classement-batch n'a été émis.
  expect(llmCalls.length).toBe(llmCallsAfterClassement);

  // ── réinjection opt-in des corrections validées comme exemples ────────────
  // Relancer le classement révèle l'option (visible car une correction
  // vient d'être capturée). Sans opt-in, le corps de /classement/batch ne porte
  // aucune correction (prompt inchangé) ; avec opt-in, la correction est envoyée
  // au moteur (qui en formule le few-shot — le front ne fait que transporter).
  await page.getByRole("button", { name: /Relancer le classement/ }).click();
  await page.getByRole("button", { name: "Relancer", exact: true }).click();

  const optIn = page.getByLabel(/Réutiliser ma correction comme exemple/);
  await expect(optIn).toBeVisible();

  // Capture le corps du prochain /classement/batch.
  const batchWithCorrections = page.waitForRequest(
    (req) =>
      req.url().includes("/api/py/classement/batch") && req.method() === "POST",
  );
  await optIn.click(); // active la réinjection
  await page.getByRole("button", { name: "Lancer le classement" }).click();

  const body = JSON.parse((await batchWithCorrections).postData() ?? "{}");
  expect(Array.isArray(body.corrections)).toBe(true);
  expect(body.corrections).toHaveLength(1);
  expect(body.corrections[0]).toMatchObject({
    path: "divers/note service.doc",
    targetFolder: "3_Vie_scolaire",
  });
});
