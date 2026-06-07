import type { NextConfig } from "next";

// Le proxy vers le backend Python est un Route Handler catch-all
// (app/api/py/[...path]/route.ts) — et non un `rewrite` — car les rewrites
// bufferisent les réponses et cassent le streaming SSE (audit / classement).
const nextConfig: NextConfig = {
  devIndicators: false,
};

export default nextConfig;
