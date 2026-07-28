import type { NextConfig } from "next";

// Le proxy vers le backend Python est un Route Handler catch-all
// (app/api/py/[...path]/route.ts) — et non un `rewrite` — car les rewrites
// bufferisent les réponses et cassent le streaming SSE (audit / classement).
// `output: "standalone"` n'est activé que pour le build Docker via
// NEXT_OUTPUT=standalone : il produit `.next/standalone` (serveur Node autonome,
// image légère). Laissé indéfini en dev/CI pour ne rien changer aux flux
// existants (`npm run dev`, `npm run build`, Playwright).
const nextConfig: NextConfig = {
  devIndicators: false,
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
};

export default nextConfig;
