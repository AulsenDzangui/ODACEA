#!/usr/bin/env node
// Build du front pour le mode tout-en-un : export statique (`next build`,
// NEXT_OUTPUT=export) servi ensuite par FastAPI same-origin (ODACEA_STATIC_DIR).
//
// `app/api/py/[...path]/route.ts` est un Route Handler dynamique (streaming
// SSE) — incompatible avec `output: "export"`, qui n'accepte que des routes
// statiques. Il n'a plus de raison d'être en mode tout-en-un (le front appelle
// FastAPI directement, NEXT_PUBLIC_API_BASE=""), donc on le déplace hors de
// l'arbre le temps du build, puis on le restaure (y compris si le build
// échoue) — jamais supprimé du dépôt : Docker et la démo en ont besoin.
//
// Outillage de build pur, aucune logique métier — au même titre que
// scripts/tree_to_archifiltre_csv.py côté backend.
import { existsSync, renameSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const apiDir = path.join(webRoot, "app", "api");
const apiDirBackup = path.join(webRoot, "app", "_api.desktop-build-backup");
const nextCacheDir = path.join(webRoot, ".next");

// Windows verrouille transitoirement un dossier surveillé par un watcher (un
// `next dev` du même repo en tâche de fond, un antivirus, l'indexeur) : EPERM/
// EBUSY sur le rename n'y signale pas un conflit réel, juste une fenêtre de
// contention. Quelques tentatives espacées suffisent ; ne JAMAIS retenter sur
// autre chose qu'EPERM/EBUSY (une vraie erreur doit remonter tout de suite).
function renameWithRetry(from, to, attempts = 10, delayMs = 300) {
  for (let i = 1; i <= attempts; i++) {
    try {
      renameSync(from, to);
      return;
    } catch (err) {
      const transient = err && (err.code === "EPERM" || err.code === "EBUSY");
      if (!transient || i === attempts) throw err;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, delayMs);
    }
  }
}

function moveOut() {
  if (existsSync(apiDirBackup)) {
    throw new Error(
      `${apiDirBackup} existe déjà — un précédent build a-t-il échoué sans restaurer ? ` +
        "Vérifiez à la main avant de relancer.",
    );
  }
  if (existsSync(apiDir)) renameWithRetry(apiDir, apiDirBackup);
}

function restore() {
  if (existsSync(apiDirBackup)) {
    renameWithRetry(apiDirBackup, apiDir);
  }
}

moveOut();
// `.next/` peut porter des artefacts d'un `next dev`/`next build` antérieur
// (typegen de validation des routes, notamment) qui référencent encore
// `app/api/py/[...path]` — invalides une fois ce dossier déplacé, et Next ne
// les régénère pas tout seul. Un build export part donc toujours d'un cache
// vide (coût : un rebuild complet, pas un problème pour un artefact de
// release construit une fois par tag).
if (existsSync(nextCacheDir)) rmSync(nextCacheDir, { recursive: true, force: true });

let result;
try {
  // Windows n'exécute un `.cmd` (le wrapper npm de `npx`) qu'au travers d'un
  // shell — `shell: true` est donc requis là, mais avec un tableau `args`
  // séparé Node avertit (DEP0190) que ces arguments ne sont pas échappés pour
  // le shell. Ils sont ici constants (jamais dérivés d'une entrée externe) :
  // on les passe fondus dans la commande plutôt que dans `args`, ce qui évite
  // l'avertissement sans rien changer côté sécurité.
  result = spawnSync("npx next build", [], {
    cwd: webRoot,
    stdio: "inherit",
    shell: true,
    env: {
      ...process.env,
      NEXT_OUTPUT: "export",
      NEXT_PUBLIC_API_BASE: "",
      NEXT_TELEMETRY_DISABLED: "1",
    },
  });
} finally {
  restore();
}

if (!result || result.status !== 0) {
  process.exit(result?.status ?? 1);
}

console.log("✓ Export statique du front (mode tout-en-un) → web/out/");
