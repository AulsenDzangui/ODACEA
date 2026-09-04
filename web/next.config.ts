import type { NextConfig } from "next";

// Le proxy vers le backend Python est un Route Handler catch-all
// (app/api/py/[...path]/route.ts) — et non un `rewrite` — car les rewrites
// bufferisent les réponses et cassent le streaming SSE (audit / classement).
// `output: "standalone"` n'est activé que pour le build Docker via
// NEXT_OUTPUT=standalone : il produit `.next/standalone` (serveur Node autonome,
// image légère). Laissé indéfini en dev/CI pour ne rien changer aux flux
// existants (`npm run dev`, `npm run build`, Playwright).
//
// `output: "export"` (NEXT_OUTPUT=export) sert le mode tout-en-un :
// export statique servi par FastAPI same-origin (`ODACEA_STATIC_DIR`), plus
// de serveur Node. Incompatible avec le Route Handler dynamique
// `app/api/py/[...path]` (streaming SSE) — le script qui pilote ce build
// (`scripts/build-desktop-export.mjs`) le déplace hors de l'arbre le temps du
// build. `trailingSlash: true` fait émettre `docs/index.html` plutôt que
// `docs.html`, la convention attendue par `StaticFiles(html=True)` côté
// FastAPI (backend/api/main.py).
const output =
  process.env.NEXT_OUTPUT === "standalone"
    ? "standalone"
    : process.env.NEXT_OUTPUT === "export"
      ? "export"
      : undefined;

const nextConfig: NextConfig = {
  devIndicators: false,
  output,
  ...(output === "export" ? { trailingSlash: true } : {}),
};

export default nextConfig;
