// Proxy same-origin vers le backend Python (FastAPI). On renvoie directement le
// ReadableStream de la réponse amont : contrairement aux `rewrites` de Next, un
// Route Handler ne bufferise pas le flux, ce qui préserve le streaming SSE
// (étapes audit / classement).
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// URL du backend. On tolère une valeur sans schéma (ex. Render `fromService`
// renvoie juste l'hôte) en préfixant https:// par défaut.
function normalizeApiUrl(raw: string): string {
  const v = raw.trim();
  if (/^https?:\/\//i.test(v)) return v.replace(/\/$/, "");
  return `https://${v.replace(/\/$/, "")}`;
}
const API_URL = normalizeApiUrl(
  process.env.ODACEA_API_URL ?? "http://127.0.0.1:8000",
);
// Secret partagé injecté côté serveur (jamais exposé au navigateur) : le backend
// l'exige en mode démo pour refuser les appels directs qui contourneraient ce
// proxy. Vide en dev → le backend ne l'exige pas non plus.
const DEMO_PROXY_SECRET = process.env.DEMO_PROXY_SECRET ?? "";

/** IP réelle du visiteur, telle que vue par le service web (Render / proxy).
 *  On prend le **dernier** maillon de X-Forwarded-For — celui ajouté par l'edge
 *  de confiance — et non le premier, qui est fourni par le client donc
 *  falsifiable (un visiteur pourrait poser son propre X-Forwarded-For pour
 *  contourner le quota par IP). */
function clientIp(req: Request): string {
  const xff = req.headers.get("x-forwarded-for");
  if (xff) {
    const parts = xff.split(",").map((p) => p.trim()).filter(Boolean);
    if (parts.length) return parts[parts.length - 1];
  }
  return req.headers.get("x-real-ip") ?? "";
}

async function proxy(
  req: Request,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await ctx.params;
  const target = `${API_URL}/${path.join("/")}`;

  const headers: Record<string, string> = {
    "Content-Type": req.headers.get("content-type") ?? "application/json",
  };
  if (DEMO_PROXY_SECRET) headers["X-Demo-Proxy-Secret"] = DEMO_PROXY_SECRET;
  // Transmet l'IP du visiteur au backend (quota par IP en démo) via un en-tête
  // dédié : le backend s'y fie car la requête est authentifiée par le secret
  // proxy ci-dessus. On évite X-Forwarded-For, que l'edge du backend remanierait.
  const ip = clientIp(req);
  if (ip) headers["X-Demo-Client-IP"] = ip;

  const init: RequestInit = {
    method: req.method,
    headers,
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
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
