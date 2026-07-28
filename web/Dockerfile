# Image du front Next.js d'ODACEA (présentation seule ; le métier vit dans le
# backend Python). Build multi-étapes → serveur Node autonome `standalone`
# (image légère). Voir compose.yml à la racine et docs/INSTALLATION_ONPREM.md.

# ── Étape 1 : build ──────────────────────────────────────────────────────────
FROM node:22-slim AS builder
WORKDIR /app

# Dépendances figées par le lockfile (couche cachée tant qu'il ne bouge pas).
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# NEXT_OUTPUT=standalone active `output: "standalone"` (cf. next.config.ts) :
# produit `.next/standalone` (serveur Node autonome). `public/` peut ne pas
# exister — on le crée pour fiabiliser la copie en étape 2.
ENV NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
RUN mkdir -p public && npm run build

# ── Étape 2 : exécution ──────────────────────────────────────────────────────
FROM node:22-slim AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=9000 \
    HOSTNAME=0.0.0.0

# Le serveur standalone embarque ses propres node_modules (traçés par Next).
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Utilisateur non-root.
RUN useradd --create-home --uid 10001 odacea
USER odacea

EXPOSE 9000

CMD ["node", "server.js"]
