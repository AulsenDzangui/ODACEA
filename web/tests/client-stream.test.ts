// Tests unitaires de lib/llm/client-stream.ts : découpage des événements
// SSE, mapUsage, taxonomie ApiError, interruption (AbortSignal). fetch est
// mocké — aucun réseau.
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  applyClassement,
  applyPreview,
  comparePlans,
  enrichCsv,
  formatApiError,
  getJson,
  mapUsage,
  parseFromFolder,
  planFromFile,
  planFromFolder,
  planMaterialize,
  postJson,
  referencePlanFromCsv,
  streamSse,
  unmapUsage,
} from "@/lib/llm/client-stream";

function sseResponse(events: object[], chunkSize = 24): Response {
  const payload = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  const bytes = new TextEncoder().encode(payload);
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let i = 0; i < bytes.length; i += chunkSize) {
        controller.enqueue(bytes.slice(i, i + chunkSize));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

afterEach(() => vi.unstubAllGlobals());

// ── mapUsage ─────────────────────────────────────────────────────────────────

describe("mapUsage", () => {
  it("convertit l'usage Python snake_case en LlmUsage", () => {
    expect(
      mapUsage({
        input_tokens: 100,
        output_tokens: 20,
        total_tokens: 120,
        cache_read_tokens: 5,
        reasoning_tokens: null,
      }),
    ).toEqual({
      inputTokens: 100,
      outputTokens: 20,
      totalTokens: 120,
      inputDetails: { cacheReadTokens: 5 },
      outputDetails: { reasoningTokens: undefined },
    });
  });

  it("retourne null sur entrée absente", () => {
    expect(mapUsage(null)).toBeNull();
    expect(mapUsage(undefined)).toBeNull();
  });
});

// ── unmapUsage (transport vers la forme moteur /journal) ──────────────────────

describe("unmapUsage", () => {
  it("ré-aplatit un LlmUsage vers la forme snake_case du moteur", () => {
    expect(
      unmapUsage({
        inputTokens: 100,
        outputTokens: 20,
        totalTokens: 120,
        inputDetails: { cacheReadTokens: 5 },
        outputDetails: { reasoningTokens: 8 },
      }),
    ).toEqual({
      input_tokens: 100,
      output_tokens: 20,
      total_tokens: 120,
      cache_read_tokens: 5,
      reasoning_tokens: 8,
    });
  });

  it("omet les champs absents plutôt que d'émettre des zéros factices", () => {
    expect(unmapUsage({ inputTokens: 10, totalTokens: 10 })).toEqual({
      input_tokens: 10,
      total_tokens: 10,
    });
  });

  it("est l'inverse de mapUsage (aller-retour sans perte)", () => {
    const py = {
      input_tokens: 1,
      output_tokens: 2,
      total_tokens: 3,
      cache_read_tokens: 4,
      reasoning_tokens: 5,
    };
    expect(unmapUsage(mapUsage(py))).toEqual(py);
  });

  it("retourne null sur entrée absente", () => {
    expect(unmapUsage(null)).toBeNull();
    expect(unmapUsage(undefined)).toBeNull();
  });
});

// ── streamSse ────────────────────────────────────────────────────────────────

describe("streamSse", () => {
  it("découpe le flux et restitue texte, raisonnement, progress, notice et done", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          { type: "reasoning", delta: "je pense" },
          { type: "notice", message: "nouvelle tentative 1/2" },
          { type: "text", delta: "Bonjour " },
          { type: "progress", batch: 0, totalBatches: 0, itemsDone: 3 },
          { type: "text", delta: "monde" },
          {
            type: "done",
            report: "Bonjour monde",
            durationMs: 42,
            usage: { input_tokens: 10, output_tokens: 2, total_tokens: 12 },
          },
        ]),
      ),
    );

    const seen: string[] = [];
    const result = await streamSse("/audit", {}, {
      onText: (d) => seen.push(`t:${d}`),
      onReasoning: (d) => seen.push(`r:${d}`),
      onNotice: (m) => seen.push(`n:${m}`),
      onProgress: (p) => seen.push(`p:${p.itemsDone}`),
    });

    expect(result.text).toBe("Bonjour monde");
    expect(result.reasoning).toBe("je pense");
    expect(result.aborted).toBe(false);
    expect(result.done?.report).toBe("Bonjour monde");
    expect(result.done?.durationMs).toBe(42);
    expect(result.usage?.totalTokens).toBe(12);
    expect(seen).toEqual([
      "r:je pense",
      "n:nouvelle tentative 1/2",
      "t:Bonjour ",
      "p:3",
      "t:monde",
    ]);
  });

  it("restitue les appels d'outils de l'agent (tool/toolResult)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          {
            type: "tool",
            step: 1,
            name: "compter",
            arguments: { filtre: { extension: "pdf" } },
          },
          {
            type: "toolResult",
            step: 1,
            name: "compter",
            result: { total: 42 },
          },
          { type: "text", delta: "42 fichiers PDF." },
          {
            type: "done",
            answer: "42 fichiers PDF.",
            steps: 1,
            usage: { input_tokens: 10, output_tokens: 2, total_tokens: 12 },
          },
        ]),
      ),
    );

    const tools: unknown[] = [];
    const result = await streamSse(
      "/agt/chat",
      {},
      { onTool: (e) => tools.push(e) },
    );

    expect(tools).toEqual([
      {
        kind: "call",
        step: 1,
        name: "compter",
        arguments: { filtre: { extension: "pdf" } },
      },
      { kind: "result", step: 1, name: "compter", result: { total: 42 } },
    ]);
    expect(result.text).toBe("42 fichiers PDF.");
  });

  it("propage l'événement error en ApiError {code, hint}", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          { type: "text", delta: "début" },
          {
            type: "error",
            message: "Clé API invalide",
            code: "llm_auth",
            hint: "Corrigez la clé.",
          },
        ]),
      ),
    );

    const onError = vi.fn();
    await expect(streamSse("/audit", {}, { onError })).rejects.toMatchObject({
      message: "Clé API invalide",
      code: "llm_auth",
      hint: "Corrigez la clé.",
    });
    expect(onError).toHaveBeenCalledOnce();
    expect(onError.mock.calls[0][0]).toBeInstanceOf(ApiError);
  });

  it("réponse HTTP non-ok : ApiError construite depuis le corps JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: "Quota atteint",
              code: "demo_quota",
              hint: "Réessayez demain.",
            }),
            { status: 429 },
          ),
      ),
    );
    await expect(streamSse("/audit", {})).rejects.toMatchObject({
      code: "demo_quota",
    });
  });

  it("interruption avant réponse : résultat vide marqué aborted", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new DOMException("abandon", "AbortError");
      }),
    );
    const result = await streamSse("/audit", {});
    expect(result).toEqual({
      text: "",
      reasoning: "",
      usage: null,
      done: null,
      aborted: true,
    });
  });

  it("interruption en cours de flux : conserve le texte déjà accumulé", async () => {
    // Réponse minimale {ok, body} : undici (Node) ferait échouer le corps entier
    // avant livraison du premier chunk, contrairement au navigateur.
    let pulls = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulls += 1;
        if (pulls === 1) {
          controller.enqueue(
            new TextEncoder().encode('data: {"type":"text","delta":"partiel"}\n\n'),
          );
        } else {
          controller.error(new DOMException("abandon", "AbortError"));
        }
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, body: stream }) as Response),
    );
    const result = await streamSse("/classement/batch", {});
    expect(result.aborted).toBe(true);
    expect(result.text).toBe("partiel");
  });

  it("ignore les lignes non-SSE et les payloads JSON invalides", async () => {
    const body = 'garbage\ndata: pas du json\ndata: {"type":"text","delta":"ok"}\n\n';
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(body));
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(stream, { status: 200 })));
    const result = await streamSse("/audit", {});
    expect(result.text).toBe("ok");
  });
});

// ── postJson / formatApiError ────────────────────────────────────────────────

describe("postJson", () => {
  it("lève ApiError quand le corps 200 porte un champ error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ error: "Aucune ligne", code: "no_llm_rows", hint: "Relancez." }),
            { status: 200 },
          ),
      ),
    );
    await expect(postJson("/classement/finalize", {})).rejects.toMatchObject({
      code: "no_llm_rows",
      hint: "Relancez.",
    });
  });

  it("retourne le JSON typé en succès", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ total: 6 }), { status: 200 })),
    );
    await expect(postJson<{ total: number }>("/classement/prepare", {})).resolves.toEqual({
      total: 6,
    });
  });
});

// ── — import direct d'un dossier / application physique ───────────────────────

describe("parseFromFolder", () => {
  it("poste le chemin à /parse/from-folder et renvoie CSV dérivé + scan", async () => {
    let seenUrl = "";
    let seenBody: unknown = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        seenUrl = url;
        seenBody = JSON.parse(init.body as string);
        return new Response(
          JSON.stringify({
            rows: [],
            validationErrors: [],
            derivedCsv: "ID;ParentID\n",
            scan: { itemCount: 3, folderCount: 2, rootTitle: "F", excludedCount: 0, skippedSymlinks: 0 },
          }),
          { status: 200 },
        );
      }),
    );
    const res = await parseFromFolder({
      sourceRoot: "D:/vrac",
      prep: {},
      batchSize: 0,
    });
    expect(seenUrl).toContain("/parse/from-folder");
    expect(seenBody).toMatchObject({ sourceRoot: "D:/vrac" });
    expect(res.scan.itemCount).toBe(3);
    expect(res.derivedCsv).toContain("ID;ParentID");
  });
});

describe("applyPreview / applyClassement", () => {
  it("applyPreview renvoie le plan de copie", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({ total: 2, missingCount: 0, targetGuard: null }),
          { status: 200 },
        ),
      ),
    );
    const p = await applyPreview([{ a: "b" }], "D:/src", "D:/out", false);
    expect(p.total).toBe(2);
    expect(p.targetGuard).toBeNull();
  });

  it("applyClassement remonte la progression de copie (copied/total/current)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse([
          { type: "progress", copied: 1, skipped: 0, failed: 0, total: 2, current: "a/x.pdf" },
          { type: "progress", copied: 2, skipped: 0, failed: 0, total: 2, current: "b/y.pdf" },
          { type: "done", stats: { total: 2, copied: 2, skipped: 0, failed: 0, errors: [], targetRoot: "D:/out" } },
        ]),
      ),
    );
    const seen: number[] = [];
    const res = await applyClassement(
      { rows: [{ a: "b" }], sourceRoot: "D:/src", targetRoot: "D:/out", resume: false, confirm: true },
      { onProgress: (p) => { if (typeof p.copied === "number") seen.push(p.copied); } },
    );
    expect(seen).toEqual([1, 2]);
    const done = res.done as { stats: { copied: number } };
    expect(done.stats.copied).toBe(2);
  });
});

describe("formatApiError", () => {
  it("ajoute le hint sur une seconde ligne", () => {
    expect(formatApiError(new ApiError("Erreur.", "x", "Faites ceci."))).toBe(
      "Erreur.\n→ Faites ceci.",
    );
    expect(formatApiError(new Error("Brut"))).toBe("Brut");
    expect(formatApiError("texte")).toBe("texte");
  });
});

// ── getJson / fetchReferencePlans ────────────────────────────────────────────

describe("getJson", () => {
  it("retourne le JSON typé en succès", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 })),
    );
    await expect(getJson<{ ok: boolean }>("/reference-plans")).resolves.toEqual({
      ok: true,
    });
  });

  it("lève ApiError quand la réponse HTTP est non-ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ error: "Indisponible", code: "x" }), {
            status: 500,
          }),
      ),
    );
    await expect(getJson("/reference-plans")).rejects.toMatchObject({
      code: "x",
    });
  });
});

// ── enrichCsv ────────────────────────────────────────────────────────────────

describe("enrichCsv", () => {
  it("poste vers /enrich et renvoie le CSV enrichi + rapports", async () => {
    const payload = {
      enrichedCsv: "ID;File\n1;.\n",
      contentAccessNotice: "Lecture locale du contenu…",
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
    };
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        new Response(JSON.stringify(payload), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      enrichCsv({
        csv: "ID;File\n1;.\n",
        sourceRoot: "/vrac",
        overwrite: false,
        fingerprint: true,
      }),
    ).resolves.toEqual(payload);

    // Transport : le corps part bien en camelCase vers /enrich.
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/enrich");
    expect(JSON.parse(init!.body as string)).toEqual({
      csv: "ID;File\n1;.\n",
      sourceRoot: "/vrac",
      overwrite: false,
      fingerprint: true,
    });
  });

  it("propage l'ApiError du refus en démonstration (enrich_disabled)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: "Enrichissement indisponible en mode démonstration.",
              code: "enrich_disabled",
              hint: "Installez ODACEA en local.",
            }),
            { status: 403 },
          ),
      ),
    );
    await expect(
      enrichCsv({ csv: "", sourceRoot: "/x", overwrite: false, fingerprint: false }),
    ).rejects.toMatchObject({ code: "enrich_disabled" });
  });
});

// ── comparePlans ─────────────────────────────────────────────────────────────

describe("comparePlans", () => {
  it("poste les plans vers /plan-compare et renvoie la comparaison du moteur", async () => {
    const payload = {
      variants: [
        {
          index: 1,
          planExtracted: true,
          folders: 2,
          depth: 1,
          maxWidth: 2,
          leaves: 2,
          folderLabels: ["cantine", "inscriptions"],
          uniqueFolders: ["inscriptions"],
        },
        {
          index: 2,
          planExtracted: true,
          folders: 2,
          depth: 1,
          maxWidth: 2,
          leaves: 2,
          folderLabels: ["cantine", "vie scolaire"],
          uniqueFolders: ["vie scolaire"],
        },
      ],
      comparison: {
        variantCount: 2,
        commonFolders: ["cantine"],
        commonFolderCount: 1,
        allFolders: ["cantine", "inscriptions", "vie scolaire"],
        identical: false,
        folderCountRange: { min: 2, max: 2 },
        depthRange: { min: 1, max: 1 },
        leavesRange: { min: 2, max: 2 },
      },
      markdown: "Variante …",
    };
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        new Response(JSON.stringify(payload), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(comparePlans(["plan A", "plan B"])).resolves.toEqual(payload);

    // Transport pur : les plans partent bien dans le corps vers /plan-compare.
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/plan-compare");
    expect(JSON.parse(init!.body as string)).toEqual({
      plans: ["plan A", "plan B"],
    });
  });

  it("propage une ApiError du backend", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ error: "boom", code: "x" }), {
            status: 500,
          }),
      ),
    );
    await expect(comparePlans(["a"])).rejects.toBeInstanceOf(ApiError);
  });
});

describe("referencePlanFromCsv", () => {
  it("renvoie l'arborescence convertie par le moteur", async () => {
    const payload = {
      tree: "```text\nFonds → F/\n```",
      validationErrors: [],
      warnings: ["1 ligne(s) fichier (Item) ignorée(s)"],
      folderCount: 3,
      ignoredItemCount: 1,
      rootTitle: "Fonds",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 })),
    );
    await expect(referencePlanFromCsv("csv")).resolves.toEqual(payload);
  });

  it("propage une ApiError sur CSV illisible (400)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ error: "boom", code: "csv_unreadable", hint: "…" }),
            { status: 400 },
          ),
      ),
    );
    await expect(referencePlanFromCsv("csv")).rejects.toBeInstanceOf(ApiError);
  });
});

// ── — plan souverain (transport pur) ─────────────────────────────────────────

describe("planFromFile", () => {
  it("transmet nom + contenu et renvoie le plan adopté", async () => {
    const payload = {
      plan: "```text\nFonds → F/\n```",
      planTree: { "1_X": null },
      folderCount: 1,
      ignoredItemCount: 0,
      rootTitle: "Fonds",
      warnings: [],
      format: "csv",
    };
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        new Response(JSON.stringify(payload), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(planFromFile("p.csv", "ID;ParentID")).resolves.toEqual(payload);
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init!.body as string)).toEqual({
      name: "p.csv",
      content: "ID;ParentID",
    });
  });

  it("propage une ApiError sur plan inexploitable (400)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ error: "boom", code: "plan_unreadable", hint: "…" }),
            { status: 400 },
          ),
      ),
    );
    await expect(planFromFile("x.md", "rien")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("planMaterialize / planFromFolder", () => {
  it("envoie les garde-fous clear/confirm à /plan/materialize", async () => {
    const fetchMock = vi.fn(
      async (_url: string, _init?: RequestInit) =>
        new Response(
          JSON.stringify({ folderCount: 3, workDir: "D:/w", cleared: true }),
          { status: 200 },
        ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const res = await planMaterialize("plan", "D:/w", { clear: true, confirm: true });
    expect(res.cleared).toBe(true);
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init!.body as string)).toEqual({
      planValide: "plan",
      workDir: "D:/w",
      clear: true,
      confirm: true,
    });
  });

  it("renvoie le plan re-scanné et l'aperçu des changements", async () => {
    const payload = {
      plan: "```text\nFonds → F/\n```",
      planTree: { "1_X": null },
      folderCount: 1,
      ignoredFileCount: 2,
      rootTitle: "Fonds",
      warnings: ["2 fichier(s) ignoré(s)"],
      changes: {
        added: ["Nouveau"],
        removed: [],
        renamed: [{ from: "A", to: "B" }],
        moved: [],
        unchanged: 1,
        identical: false,
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 })),
    );
    const res = await planFromFolder("D:/w", "plan actuel");
    expect(res.changes?.renamed[0]).toEqual({ from: "A", to: "B" });
    expect(res.ignoredFileCount).toBe(2);
  });

  it("propage une ApiError quand l'endpoint est refusé (403 démo)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ error: "refusé", code: "plan_local_only", hint: "…" }),
            { status: 403 },
          ),
      ),
    );
    await expect(planMaterialize("p", "D:/w")).rejects.toBeInstanceOf(ApiError);
  });
});
