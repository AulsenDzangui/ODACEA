"use client";

import { useWizard } from "@/lib/store";
import { DEFAULT_LOCAL_ENDPOINTS, DEMO_MODE } from "@/lib/llm/config";
import { useBackendHealth, type HealthStatus } from "@/lib/backend-health";
import { useT } from "@/lib/i18n";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertTriangle } from "lucide-react";

// ── Barre d'état unique (D8) ─────────────────────────────────────────────────
// Indicateur permanent consolidant connexion backend + modèle actif (remplace
// model-badge + backend-health-alert). `StatusPill` vit dans l'en-tête (toujours
// visible) ; `BackendDownBanner` ajoute le message actionnable quand le backend
// est confirmé injoignable. Les deux partagent la même sonde (useBackendHealth).

// Modèle imposé côté serveur en démonstration (cf. DEMO_MODEL backend).
const DEMO_MODEL_LABEL = "gpt-5.4-mini";

const ENDPOINT_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(DEFAULT_LOCAL_ENDPOINTS).map(([name, url]) => [url, name]),
);

function deriveLocalLabel(localModel: string, localEndpoint: string): string {
  const model = localModel.trim();
  if (model) {
    return model.includes("/") ? model.split("/").slice(1).join("/") : model;
  }
  const endpoint = localEndpoint.trim() || DEFAULT_LOCAL_ENDPOINTS["LM Studio"];
  if (ENDPOINT_LABELS[endpoint]) return ENDPOINT_LABELS[endpoint];
  try {
    return new URL(endpoint).host;
  } catch {
    return endpoint;
  }
}

const HEALTH_DOT: Record<HealthStatus, string> = {
  healthy: "bg-emerald-500",
  down: "bg-(--danger-500) animate-pulse",
  unknown: "bg-(--ink-300)",
};

export function StatusPill() {
  const t = useT();
  const providerMode = useWizard((s) => s.providerMode);
  const cloudModel = useWizard((s) => s.cloudModel);
  const localModel = useWizard((s) => s.localModel);
  const localEndpoint = useWizard((s) => s.localEndpoint);
  const health = useBackendHealth();

  const healthText: Record<HealthStatus, string> = {
    healthy: t.status.healthy,
    down: t.status.down,
    unknown: t.status.unknown,
  };

  const isLocal = providerMode === "local";

  const modelLabel = DEMO_MODE
    ? DEMO_MODEL_LABEL
    : isLocal
      ? deriveLocalLabel(localModel, localEndpoint)
      : cloudModel.includes("/")
        ? cloudModel.split("/").slice(1).join("/")
        : cloudModel;

  const modelFull = DEMO_MODE
    ? `${DEMO_MODEL_LABEL} (imposé en démonstration)`
    : isLocal
      ? localModel.trim() || localEndpoint.trim() || "local"
      : cloudModel;

  const providerLabel = DEMO_MODE
    ? t.status.providerDemo
    : isLocal
      ? t.status.providerLocal
      : t.status.providerCloud;

  return (
    <span
      className="hidden items-center gap-2 rounded-full border border-border bg-background px-2.5 py-1 text-xs text-muted-foreground sm:inline-flex"
      title={`${healthText[health]} · ${providerLabel} · modèle : ${modelFull}`}
    >
      <span className="flex items-center gap-1.5">
        <span
          className={`h-1.5 w-1.5 rounded-full ${HEALTH_DOT[health]}`}
          aria-hidden="true"
        />
        <span className="sr-only">{healthText[health]} — </span>
        <span className="text-(--ink-400)">{providerLabel}</span>
      </span>
      <span className="h-3 w-px bg-border" aria-hidden="true" />
      <span className="font-medium text-(--ink-700)">{modelLabel}</span>
    </span>
  );
}

export function BackendDownBanner() {
  const t = useT();
  const health = useBackendHealth();
  if (health !== "down") return null;
  return (
    <Alert variant="destructive" className="mx-5 mb-4 mt-4">
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>{t.status.backendDownTitle}</AlertTitle>
      <AlertDescription>{t.status.backendDownBody}</AlertDescription>
    </Alert>
  );
}
