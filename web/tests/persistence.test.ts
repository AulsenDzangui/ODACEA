import { beforeEach, describe, expect, it } from "vitest";

// localStorage minimal en mémoire — persistence.ts ne touche au stockage que
// via window.localStorage (env node, pas de DOM).
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

// @ts-expect-error — installe un faux window pour le module client.
globalThis.window = { localStorage: new MemoryStorage() };

const {
  saveProject,
  loadProject,
  listProjects,
  exportProjectJson,
  importProjectJson,
  estimateStorageUsage,
  saveLlmConfig,
  loadLlmConfig,
  saveUiPrefs,
  loadUiPrefs,
} = await import("@/lib/persistence");

const LLM_CONFIG_KEY = "odacea-llm-config";

const snapshot = () =>
  ({
    csvFilename: "vrac.csv",
    csvOriginal: [{ ID: "1", File: "." }],
    archivisteObservation: "",
    step: "audit" as const,
    rapportAudit: "Rapport",
    thinkingAudit: "",
    planValide: "1. A → 1_A/",
    planValideOriginal: "1. A → 1_A/",
    planNotes: "",
    planModifie: false,
    briefMode: false,
    thinkingClassement: "",
    llmRawResponse: "",
    llmRawRows: null,
    classementBatches: null,
    csvFinal: null,
    lastError: "",
  }) as Parameters<typeof saveProject>[1];

beforeEach(() => {
  (window.localStorage as unknown as MemoryStorage).clear();
});

describe("export / import projet (D9)", () => {
  it("round-trip : un projet exporté se réimporte sous un nom libre", () => {
    const stem = saveProject("Mon fonds", snapshot());
    const { filename, json } = exportProjectJson(stem);
    expect(filename).toBe("Mon_fonds.odacea.json");

    const { stem: newStem, name } = importProjectJson(json);
    // Le stem d'origine est pris → l'import est suffixé, jamais écrasé.
    expect(newStem).not.toBe(stem);
    expect(name).toBe("Mon fonds (2)");
    expect(listProjects()).toHaveLength(2);
  });

  it("conserve le modèle figé par étape à travers l'export/import (traçabilité)", () => {
    const snap = {
      ...snapshot(),
      modelAudit: "claude-opus-4-8",
      modelClassement: "ollama/llama3",
    } as Parameters<typeof saveProject>[1];
    const stem = saveProject("Fonds tracé", snap);
    const { json } = exportProjectJson(stem);
    const { stem: newStem } = importProjectJson(json);

    const reloaded = loadProject(newStem);
    expect(reloaded?.modelAudit).toBe("claude-opus-4-8");
    expect(reloaded?.modelClassement).toBe("ollama/llama3");
  });

  it("conserve les consignes de classement à travers l'export/import", () => {
    const snap = {
      ...snapshot(),
      classementDirectives: [
        { text: "un sous-dossier par employeur", folder: "1_A", allowCreation: true },
        { text: "nommer en français", allowCreation: false },
      ],
    } as Parameters<typeof saveProject>[1];
    const stem = saveProject("Fonds consignes", snap);
    const { json } = exportProjectJson(stem);
    const { stem: newStem } = importProjectJson(json);
    const reloaded = loadProject(newStem);
    expect(reloaded?.classementDirectives).toEqual([
      { text: "un sous-dossier par employeur", folder: "1_A", allowCreation: true },
      { text: "nommer en français", allowCreation: false },
    ]);
  });

  it("rejette un fichier qui n'est pas un export ODACEA", () => {
    expect(() => importProjectJson('{"foo":1}')).toThrow(/projet ODACEA/);
    expect(() => importProjectJson("pas du json")).toThrow(/JSON invalide/);
  });

  it("rejette un export d'une version plus récente", () => {
    const stem = saveProject("X", snapshot());
    const env = JSON.parse(exportProjectJson(stem).json);
    env.version = 999;
    expect(() => importProjectJson(JSON.stringify(env))).toThrow(
      /version plus récente/,
    );
  });
});

describe("clé API : mémorisation explicite", () => {
  it("ne persiste pas la clé tant que la mémorisation n'est pas activée", () => {
    saveLlmConfig({
      providerMode: "cloud",
      cloudModel: "claude-x",
      apiKey: "sk-secret",
      rememberApiKey: false,
    });
    const cfg = loadLlmConfig();
    // Les autres réglages (et la préférence elle-même) sont bien persistés…
    expect(cfg?.cloudModel).toBe("claude-x");
    expect(cfg?.rememberApiKey).toBe(false);
    // … mais pas la clé.
    expect(cfg?.apiKey).toBeUndefined();
    // Garantie au niveau du stockage brut : le secret n'apparaît nulle part.
    expect(window.localStorage.getItem(LLM_CONFIG_KEY)).not.toContain(
      "sk-secret",
    );
  });

  it("persiste la clé seulement après opt-in explicite", () => {
    saveLlmConfig({ apiKey: "sk-secret", rememberApiKey: true });
    expect(loadLlmConfig()?.apiKey).toBe("sk-secret");
    // Repasser en session-only efface le secret déjà posé sur disque.
    saveLlmConfig({ apiKey: "sk-secret", rememberApiKey: false });
    expect(loadLlmConfig()?.apiKey).toBeUndefined();
    expect(window.localStorage.getItem(LLM_CONFIG_KEY)).not.toContain(
      "sk-secret",
    );
  });
});

describe("préférences UI de traitement (lots)", () => {
  it("round-trip taille de lot + concurrence, fusionnées avec l'existant", () => {
    saveUiPrefs({ classementRef: true });
    saveUiPrefs({ classementBatchSize: 200, classementConcurrency: 3 });
    const prefs = loadUiPrefs();
    // Le merge préserve les clés déjà posées (saveUiPrefs fusionne).
    expect(prefs?.classementRef).toBe(true);
    expect(prefs?.classementBatchSize).toBe(200);
    expect(prefs?.classementConcurrency).toBe(3);
  });
});

describe("estimateStorageUsage (D9)", () => {
  it("croît avec le contenu stocké et reste borné", () => {
    expect(estimateStorageUsage().bytes).toBe(0);
    saveProject("Projet", snapshot());
    const usage = estimateStorageUsage();
    expect(usage.bytes).toBeGreaterThan(0);
    expect(usage.ratio).toBeGreaterThan(0);
    expect(usage.ratio).toBeLessThan(1);
  });
});
