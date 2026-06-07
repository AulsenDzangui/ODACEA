// Proxy same-origin vers le backend Python (FastAPI). On renvoie directement le
// ReadableStream de la réponse amont : contrairement aux `rewrites` de Next, un
// Route Handler ne bufferise pas le flux, ce qui préserve le streaming SSE
// (étapes audit / classement).
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_URL = process.env.ODACEA_API_URL ?? "http://127.0.0.1:8000";

async function proxy(
  req: Request,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await ctx.params;
  const target = `${API_URL}/${path.join("/")}`;

  const init: RequestInit = {
    method: req.method,
    headers: {
      "Content-Type": req.headers.get("content-type") ?? "application/json",
    },
    body:
      req.method === "GET" || req.method === "HEAD"
        ? undefined
        : await req.text(),
  };

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return new Response(
      JSON.stringify({
        error: `Backend Python injoignable (${API_URL}). Lancez : uvicorn api.main:app --port 8000. Détail : ${msg}`,
      }),
      { status: 502, headers: { "Content-Type": "application/json" } },
    );
  }

  // Renvoie le corps tel quel (stream pour le SSE, JSON sinon). `no-transform`
  // empêche toute compression/agrégation intermédiaire qui casserait le flux.
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type":
        upstream.headers.get("content-type") ?? "application/octet-stream",
      "Cache-Control": "no-cache, no-transform",
    },
  });
}

export const GET = proxy;
export const POST = proxy;
