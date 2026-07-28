// E2E Playwright de l'agent (UI chat, lecture seule) contre
// un backend entièrement mocké via page.route : import du CSV, session, tour
// de chat SSE (transparence des appels d'outils), réinitialisation de la
// conversation.
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const FIXTURES = path.resolve(__dirname, "../../backend/tests/fixtures");
const csvText = fs.readFileSync(
  path.join(FIXTURES, "archifiltre_small.csv"),
  "utf-8",
);
const goldenAud = fs.readFileSync(
  path.join(FIXTURES, "golden/aud_small.md"),
  "utf-8",
);

// Mini-parseur du CSV de fixture (QUOTE_ALL, séparateur ;) → lignes objets,
// comme le ferait /parse côté Python. L'agent étant lié au projet, le test doit
// d'abord charger un CSV dans le projet (étape upload) avant d'ouvrir l'agent.
function parseFixtureCsv(text: string): Record<string, string>[] {
  const lines = text.trim().split("\n");
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

function sse(events: object[]): string {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
}

let sessionCreates = 0;
// Corps des requêtes POST /agt/session observées (0.6.0 : vérifier l'envoi ou
// non du rapport d'audit selon le toggle).
let sessionBodies: Array<Record<string, unknown>> = [];

async function mockBackend(page: Page) {
  sessionCreates = 0;
  sessionBodies = [];
  await page.route("**/api/py/health", (route) =>
    route.fulfill({ json: { status: "ok" } }),
  );
  await page.route("**/api/py/models", (route) =>
    route.fulfill({
      json: { default: "gpt-test", models: ["gpt-test"], localEndpoints: {}, demoMode: false },
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
        },
      },
    }),
  );
  await page.route("**/api/py/agt/session", (route) => {
    sessionCreates += 1;
    const body = (route.request().postDataJSON() ?? {}) as Record<
      string,
      unknown
    >;
    sessionBodies.push(body);
    const auditReportUsed =
      typeof body.auditReport === "string" && body.auditReport.trim().length > 0;
    route.fulfill({
      json: {
        sessionId: `sess-${sessionCreates}`,
        stats: { rowCount: 10, itemCount: 6, recordGrpCount: 4 },
        digest: "digest",
        ttlS: 1800,
        auditReportUsed,
      },
    });
  });
  // Audit (0.6.0) : nécessaire pour peupler le rapport du projet avant d'ouvrir
  // l'agent. Le done{report} alimente `rapportAudit` du store.
  await page.route("**/api/py/audit", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: sse([
        { type: "text", delta: goldenAud },
        {
          type: "done",
          report: goldenAud,
          plan:
            goldenAud.match(
              /<!-- PLAN_STRUCTURE_START -->([\s\S]*?)<!-- PLAN_STRUCTURE_END -->/,
            )?.[1] ?? "",
          notes: "Notes pour l'archiviste.",
          planTree: { AFFAIRES_SCOLAIRES: null },
          usage: { input_tokens: 1000, output_tokens: 500, total_tokens: 1500 },
          durationMs: 1234,
          promptVersion: "1.0.0",
          model: "gpt-test",
        },
      ]),
    }),
  );
  await page.route("**/api/py/agt/chat", (route) => {
    route.fulfill({
      contentType: "text/event-stream",
      body: sse([
        {
          type: "tool",
          step: 1,
          name: "compter",
          arguments: { filtre: { dossier: "RESTAURATION" } },
        },
        {
          type: "toolResult",
          step: 1,
          name: "compter",
          result: { total: 3, filtre: { dossier: "RESTAURATION" } },
        },
        { type: "text", delta: "Le dossier RESTAURATION contient 3 fichiers." },
        {
          type: "done",
          answer: "Le dossier RESTAURATION contient 3 fichiers.",
          steps: 1,
          usage: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
          usageSession: { input_tokens: 100, output_tokens: 20, total_tokens: 120 },
          costSessionEur: 0.0028,
          toolMode: "native",
          promptVersion: "0.6.0",
          model: "gpt-test",
        },
      ]),
    });
  });
  await page.route("**/api/py/agt/session/*/history", (route) =>
    route.fulfill({ json: { sessionId: "sess-1", reset: true, turns: 0 } }),
  );
}

test(" — session et tour de chat avec transparence des outils (lecture seule)", async ({
  page,
}) => {
  await mockBackend(page);
  await page.goto("/");

  // L'agent est lié au projet courant : on charge d'abord un CSV dans le projet
  // (étape upload du wizard), puis on ouvre l'agent — la session démarre
  // automatiquement depuis ce CSV, sans étape d'import propre à l'agent.
  await page.setInputFiles('main input[type="file"]', {
    name: "vrac.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csvText),
  });
  await expect(page.getByText("Continuer vers l'audit")).toBeVisible();
  await page.getByRole("button", { name: "Agent" }).click();

  const dialog = page.getByRole("dialog");
  await expect(page.getByText(/Session créée avec 10 ligne/)).toBeVisible();

  // Tour de chat : question de recherche/navigation.
  await page
    .getByPlaceholder(/principales thématiques du fonds/)
    .fill("Combien de fichiers dans le dossier RESTAURATION ?");
  await page.getByRole("button", { name: "Envoyer" }).click();

  // Transparence : l'appel d'outil et son résultat sont affichés (deux
  // blocs <pre> distincts — arguments puis résultat — tous deux mentionnent
  // le filtre, seul le second porte le total).
  await expect(page.getByText("Outil compter")).toBeVisible();
  await page.getByText("Outil compter").click();
  const toolPre = dialog.locator("pre");
  await expect(toolPre).toHaveCount(2);
  await expect(toolPre.first()).toContainText(/"dossier": "RESTAURATION"/);
  await expect(toolPre.nth(1)).toContainText(/"total": 3/);

  // Réponse de l'agent + cumul tokens et coût € de session.
  await expect(
    page.getByText("Le dossier RESTAURATION contient 3 fichiers."),
  ).toBeVisible();
  await expect(page.getByText(/Tokens cumulés sur la session/)).toBeVisible();
  await expect(page.getByText(/Coût indicatif cumulé : < 0,01 €/)).toBeVisible();

  // Réinitialisation de la conversation : le fil se vide, la session reste ouverte.
  await page.getByRole("button", { name: /Réinitialiser la conversation/ }).click();
  await expect(
    page.getByText("Le dossier RESTAURATION contient 3 fichiers."),
  ).not.toBeVisible();
});

test("0.6.0 — le rapport d'audit du projet est donné à l'agent (toggle ON par défaut, décocher recrée sans rapport)", async ({
  page,
}) => {
  await mockBackend(page);
  await page.goto("/");

  // Upload → audit : peuple `rapportAudit` du projet.
  await page.setInputFiles('main input[type="file"]', {
    name: "vrac.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(csvText),
  });
  await page.getByText("Continuer vers l'audit").click();
  await page.getByRole("button", { name: "Lancer l'audit" }).click();
  await expect(
    page.getByText("Continuer vers le classement"),
  ).toBeEnabled();

  // Ouverture de l'agent : session créée automatiquement AVEC le rapport
  // (toggle ON par défaut), signalée dans l'UI.
  await page.getByRole("button", { name: "Agent" }).click();
  await expect(page.getByText(/Session créée avec 10 ligne/)).toBeVisible();
  await expect(
    page.getByText("L'agent a lu le rapport d'audit du projet"),
  ).toBeVisible();
  // La 1re création de session portait bien le rapport.
  expect(
    typeof sessionBodies.at(-1)?.auditReport === "string" &&
      (sessionBodies.at(-1)?.auditReport as string).length > 0,
  ).toBe(true);

  // Décocher : la session est recréée SANS rapport (le fil repart).
  const before = sessionCreates;
  await page
    .getByRole("checkbox", { name: /rapport d'audit/i })
    .uncheck();
  await expect
    .poll(() => sessionCreates)
    .toBeGreaterThan(before);
  await expect(
    page.getByText("Donner le rapport d'audit à l'agent"),
  ).toBeVisible();
  expect(sessionBodies.at(-1)?.auditReport).toBeUndefined();
});
