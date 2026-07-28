import { defineConfig } from "vitest/config";
import path from "node:path";

// Tests unitaires : environnement node — streamSse s'appuie sur fetch/
// ReadableStream natifs de Node 20+, le store Zustand est pur JS. Les tests
// E2E Playwright vivent dans e2e/ (exclus d'office).
export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname) },
  },
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
  },
});
