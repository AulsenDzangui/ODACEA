// Check backend API health and expose status for displaying warnings.

"use client";

import { useSyncExternalStore } from "react";
import { API_BASE } from "@/lib/llm/client-stream";

export type HealthStatus = "healthy" | "down" | "unknown";

// Sonde partagée (barre d'état unique, D8) : un seul intervalle process-wide
// (module singleton), quel que soit le nombre de composants consommateurs
// (StatusPill + BackendDownBanner montés simultanément) — évite de dupliquer
// les requêtes GET /health.
let sharedStatus: HealthStatus = "unknown";
const listeners = new Set<() => void>();
let pollHandle: ReturnType<typeof setInterval> | null = null;

function setStatus(s: HealthStatus) {
  if (s === sharedStatus) return;
  sharedStatus = s;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  if (listeners.size === 0) {
    const check = () => {
      checkBackendHealth().then(setStatus);
    };
    check();
    pollHandle = setInterval(check, 30000);
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && pollHandle) {
      clearInterval(pollHandle);
      pollHandle = null;
    }
  };
}

function getSnapshot(): HealthStatus {
  return sharedStatus;
}

export function useBackendHealth(): HealthStatus {
  return useSyncExternalStore(subscribe, getSnapshot, () => "unknown");
}

/**
 * Check backend health via GET /health.
 * Returns "down" on any non-OK response, network error, or timeout (5 s).
 */
export async function checkBackendHealth(): Promise<HealthStatus> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);

    const res = await fetch(`${API_BASE}/health`, {
      method: "GET",
      signal: controller.signal,
    });

    clearTimeout(timeout);

    return res.ok ? "healthy" : "down";
  } catch {
    return "down";
  }
}
