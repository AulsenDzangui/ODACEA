// E2E du tableau de bord des fonds : page locale (localStorage) qui agrège
// les projets traités. Aucun backend requis pour la lecture ; on amorce le
// stockage du navigateur avant le chargement, puis on vérifie la synthèse et
// l'accès en un clic depuis l'en-tête.
import { expect, test } from "@playwright/test";

const PROJECT = {
  name: "Fonds scolarité",
  stem: "Fonds_scolarite",
  savedAt: 1_700_000_000_000,
  csvFilename: "vrac.csv",
  csvOriginal: [
    { ID: "1", File: ".", "Content.DescriptionLevel": "RecordGrp" },
    { ID: "2", File: "a.pdf", "Content.DescriptionLevel": "Item" },
    { ID: "3", File: "b.pdf", "Content.DescriptionLevel": "Item" },
  ],
  archivisteObservation: "",
  step: "classement",
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
  csvFinal: {
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
      planFolders: 1,
      outputFolders: 1,
      foldersOffPlan: [],
      foldersMissing: [],
      itemsMalformed: 0,
      planMatches: true,
    },
  },
  lastError: "",
};

async function seedProject(page: import("@playwright/test").Page) {
  await page.addInitScript((proj) => {
    const stem = proj.stem;
    window.localStorage.setItem(
      `odacea-projects/${stem}`,
      JSON.stringify(proj),
    );
    window.localStorage.setItem(
      "odacea-projects/index",
      JSON.stringify([
        {
          stem,
          name: proj.name,
          savedAt: proj.savedAt,
          csvFilename: proj.csvFilename,
        },
      ]),
    );
  }, PROJECT);
}

function mockBackend(page: import("@playwright/test").Page) {
  return Promise.all([
    page.route("**/api/py/health", (route) =>
      route.fulfill({ json: { status: "ok" } }),
    ),
    page.route("**/api/py/models", (route) =>
      route.fulfill({
        json: {
          default: "gpt-test",
          models: ["gpt-test"],
          localEndpoints: {},
          demoMode: false,
        },
      }),
    ),
  ]);
}

test("le tableau de bord agrège les fonds traités localement", async ({
  page,
}) => {
  await seedProject(page);
  await page.goto("/tableau-de-bord");

  await expect(
    page.getByRole("heading", { name: "Statistiques de projets" }),
  ).toBeVisible();
  // Le projet amorcé apparaît, avec sa conformité dérivée des stats moteur.
  await expect(page.getByText(PROJECT.name)).toBeVisible();
  await expect(page.getByText("Conforme")).toBeVisible();
});

test("le tableau de bord est accessible en un clic depuis l'en-tête", async ({
  page,
}) => {
  await mockBackend(page);
  await seedProject(page);

  await page.goto("/");
  await page.getByRole("link", { name: "Statistiques" }).click();

  await expect(page).toHaveURL(/\/tableau-de-bord$/);
  await expect(
    page.getByRole("heading", { name: "Statistiques de projets" }),
  ).toBeVisible();
});
