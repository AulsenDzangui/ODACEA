"use client";

import { useWizard } from "@/lib/store";
import { DEFAULT_LOCAL_ENDPOINTS } from "@/lib/llm/config";

// Table inverse : URL d'endpoint → libellé du serveur.
const ENDPOINT_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(DEFAULT_LOCAL_ENDPOINTS).map(([name, url]) => [url, name])
);

function deriveLocalLabel(localModel: string, localEndpoint: string): string {
  const model = localModel.trim();
  if (model) {
    // Retire le préfixe « ollama/ » — le nom du modèle suffit.
    return model.includes("/") ? model.split("/").slice(1).join("/") : model;
  }
  // LM Studio / JAN n'exigent pas de nom de modèle : on affiche le nom du serveur déduit de l'endpoint.
  const endpoint = localEndpoint.trim() || DEFAULT_LOCAL_ENDPOINTS["LM Studio"];
  if (ENDPOINT_LABELS[endpoint]) return ENDPOINT_LABELS[endpoint];
  try {
    return new URL(endpoint).host;
  } catch {
    return endpoint;
  }
}

export function ModelBadge() {
  const providerMode = useWizard((s) => s.providerMode);
  const cloudModel = useWizard((s) => s.cloudModel);
  const localModel = useWizard((s) => s.localModel);
  const localEndpoint = useWizard((s) => s.localEndpoint);

  const isLocal = providerMode === "local";

  const label = isLocal
    ? deriveLocalLabel(localModel, localEndpoint)
    : cloudModel.includes("/")
      ? cloudModel.split("/").slice(1).join("/")
      : cloudModel;

  const fullId = isLocal
    ? localModel.trim() || localEndpoint.trim() || "local"
    : cloudModel;

  return (
    <span
      className="hidden sm:inline-flex items-center gap-1.5 rounded-full border border-border bg-background px-2.5 py-1 text-xs text-muted-foreground"
      title={`Modèle actif : ${fullId}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${isLocal ? "bg-emerald-500" : "bg-blue-400"}`}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}
