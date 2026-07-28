import { defineConfig } from "@playwright/test";

// E2E du wizard contre un backend entièrement mocké (page.route sur
// /api/py/*) : aucun appel LLM ni backend Python requis. Le serveur Next est
// lancé automatiquement.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: "http://localhost:9000",
    launchOptions: process.env.PW_CHROME
      ? { executablePath: process.env.PW_CHROME }
      : undefined,
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:9000",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
