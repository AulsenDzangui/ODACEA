import type { FolderTree } from "./types";

// ── Copie miroir documentée ───────────────────────────────────────
// Le parsing de l'arborescence technique (arborescenceBlock, parsePlanTree)
// duplique volontairement `backend/core/csv_handler.py` (`_arborescence_block`,
// `parse_plan_tree`). Raison : l'aperçu de l'arbre doit se re-rendre en direct
// pendant l'édition manuelle du plan, et rester affichable sur un projet
// persisté (localStorage) sans backend joignable. Cette copie est
// NON-AUTORITATIVE : à la conversion RESIP, le Python re-dérive l'arbre depuis
// le texte du plan — seule source de vérité. Toute évolution du format du bloc
// « Arborescence technique » doit être répercutée des deux côtés.
// (parsePlanTitles / parsePlanRootTitle / displayParts / sortKey sont de la
// présentation pure, sans équivalent Python.)

// Séparateur « titre descriptif → nom technique » sur une ligne d'arborescence.
// Le LLM écrit « → » (gabarit) mais retombe parfois sur l'ASCII « -> ».
const ARROW_RE = /\s*(?:→|->)\s*/;
// Nom technique de dossier : se termine par « / ». Recherché APRÈS la flèche
// (cf. technicalSegment) pour ne jamais confondre un mot du titre avec un dossier.
const FOLDER_RE = /([\w][\w-]*)\//;
const NUMBERING_RE = /^\d+(?:\.\d+)*\.?\s*/;
const TREE_PREFIX_RE = /^[│├└─\s]+/;
// Placeholder du gabarit pour la racine (mappée au nœud File="." côté Python) :
// jamais un vrai dossier, donc exclue de l'arbre — mais son titre descriptif
// porte l'intitulé du fonds (cf. parsePlanRootTitle).
const ROOT_PLACEHOLDER = "Dossier_racine";

// Label littéral « Fonds — » de la ligne racine du gabarit. Il est purement
// présentationnel : ré-ajouté à la sérialisation (plan-edit.ts) et au rendu
// (plan-tree.tsx). On le retire donc systématiquement à la lecture — et toutes
// ses répétitions — pour qu'il ne s'accumule pas (« Fonds — Fonds — … ») au fil
// des aller-retours édition. Em-dash (—) ou en-dash (–), seuls séparateurs émis
// par le gabarit / la sérialisation.
const FONDS_LABEL_RE = /^(?:Fonds\s*[—–]\s*)+/i;

/** Retire le label « Fonds — » (et ses répétitions) en tête d'un intitulé de fonds. */
export function stripFondsLabel(title: string): string {
  return title.replace(FONDS_LABEL_RE, "").trim();
}

// Format fusionné « titre → nom_technique/ » : ne garder que ce qui suit la
// dernière flèche. Ancien format (nom technique seul) : pas de flèche, on rend
// la ligne entière — d'où la rétro-compatibilité.
function technicalSegment(line: string): string {
  const parts = line.split(ARROW_RE);
  return parts[parts.length - 1];
}

// Bloc « Arborescence technique » du plan, ou le texte entier en repli. Le LLM
// place tantôt l'arbre dans un fence ```text``` qui suit l'en-tête, tantôt
// l'en-tête lui-même DANS le fence — on ne dépend donc pas d'un fence : on
// capture tout ce qui suit l'en-tête jusqu'à la section suivante (Préconisations)
// ou la fin. Les fences ``` sont ignorés en aval par FOLDER_RE puisqu'ils ne se
// terminent pas par « / ».
//
// Repli sans en-tête : un petit modèle qui n'a pas suivi le gabarit — ou un plan
// saisi/collé à la main — produit l'arbre sans le titre de section. Plutôt que de
// rejeter le plan (et forcer une édition manuelle), on retombe sur le texte
// entier : les lignes de dossiers « titre → nom_technique/ » restent
// identifiables par FOLDER_RE, qui ignore la prose (aucun « / » terminal).
// Miroir de backend/core/csv_handler.py::_arborescence_block.
function arborescenceBlock(planValide: string): string {
  const headerMatch = planValide.match(/[Aa]rborescence\s+technique/);
  let block =
    headerMatch && headerMatch.index !== undefined
      ? planValide.slice(headerMatch.index + headerMatch[0].length)
      : planValide;
  const stop = block.match(/[Pp]r[ée]conisation/);
  if (stop && stop.index !== undefined) {
    block = block.slice(0, stop.index);
  }
  return block;
}

export function parsePlanTree(planValide: string): FolderTree {
  const block = arborescenceBlock(planValide);

  const folders: string[] = [];
  for (const line of block.split("\n")) {
    const m = technicalSegment(line).match(FOLDER_RE);
    if (m) {
      const name = m[1];
      if (name && name.includes("_") && name !== ROOT_PLACEHOLDER) {
        folders.push(name);
      }
    }
  }

  const result: FolderTree = {};
  for (const folder of folders) {
    const prefix = folder.split("_")[0];
    const parts = prefix.split("-");
    if (parts.length === 1) {
      result[folder] = null;
    } else {
      const parentPrefix = parts.slice(0, -1).join("-");
      const parent = folders.find((f) => f.split("_")[0] === parentPrefix);
      result[folder] = parent ?? null;
    }
  }

  // S'il existe une racine non numérique à préfixe de plusieurs caractères
  // (ex. « Mairie_… »), on rattache toutes les autres racines sous elle. Les
  // dossiers à préfixe d'une seule lettre (ex. « A_trier ») sont traités comme
  // des enfants, pas comme des racines organisationnelles candidates.
  const roots = Object.keys(result).filter((f) => result[f] === null);
  const mainRoot = roots.find(
    (f) => !/^\d+/.test(f.split("_")[0]) && f.split("_")[0].length > 1,
  );
  if (mainRoot && roots.length > 1) {
    for (const f of roots) {
      if (f !== mainRoot) result[f] = mainRoot;
    }
  }

  return result;
}

// Extrait { nomTechnique: titreDescriptif } de l'arborescence fusionnée. Sur
// chaque ligne « titre → nom_technique/ », associe le nom technique à son titre
// descriptif (numérotation et caractères d'arbre retirés). Retourne un objet
// vide pour un plan à l'ancien format (sans flèche) : l'appelant retombe alors
// sur displayParts (titre dérivé du nom technique).
export function parsePlanTitles(planValide: string): Record<string, string> {
  const block = arborescenceBlock(planValide);

  const titles: Record<string, string> = {};
  for (const line of block.split("\n")) {
    const parts = line.split(ARROW_RE);
    if (parts.length < 2) continue; // pas de flèche → aucun titre associable
    const m = parts[parts.length - 1].match(FOLDER_RE);
    if (!m) continue;
    const name = m[1];
    if (!name.includes("_") || name === ROOT_PLACEHOLDER) continue;
    const title = parts[0]
      .replace(TREE_PREFIX_RE, "")
      .replace(NUMBERING_RE, "")
      .trim();
    if (title) titles[name] = title;
  }
  return titles;
}

// Intitulé descriptif du fonds : titre porté par la ligne racine
// « Fonds — … → Dossier_racine/ ». Ce nœud étant exclu de l'arbre (placeholder),
// son titre est récupéré à part pour être affiché en tête de la vue. Les
// crochets résiduels du gabarit ([Nom du fonds]) sont retirés. null si absent.
export function parsePlanRootTitle(planValide: string): string | null {
  const block = arborescenceBlock(planValide);

  for (const line of block.split("\n")) {
    const parts = line.split(ARROW_RE);
    if (parts.length < 2) continue;
    const m = parts[parts.length - 1].match(FOLDER_RE);
    if (!m || m[1] !== ROOT_PLACEHOLDER) continue;
    const title = parts[0]
      .replace(TREE_PREFIX_RE, "")
      .replace(NUMBERING_RE, "")
      .replace(/[[\]]/g, "")
      .trim();
    return stripFondsLabel(title) || null;
  }
  return null;
}

// Entrées de l'arborescence dans l'ordre du document, racine placeholder
// incluse. Base de l'éditeur structuré (lib/csv/plan-edit.ts) : contrairement à
// parsePlanTree (relations parent/enfant), on conserve ici l'ordre d'écriture
// et le titre descriptif de chaque ligne pour reconstruire un arbre éditable.
export type PlanEntry = { name: string; title: string };

export function parsePlanEntries(planValide: string): PlanEntry[] {
  const block = arborescenceBlock(planValide);

  const entries: PlanEntry[] = [];
  for (const line of block.split("\n")) {
    const parts = line.split(ARROW_RE);
    const m = parts[parts.length - 1].match(FOLDER_RE);
    if (!m) continue;
    const name = m[1];
    if (!name || !name.includes("_")) continue;
    const title =
      parts.length >= 2
        ? parts[0]
            .replace(TREE_PREFIX_RE, "")
            .replace(NUMBERING_RE, "")
            .replace(/[[\]]/g, "")
            .trim()
        : "";
    entries.push({ name, title });
  }
  return entries;
}

export type DisplayParts = { number: string; label: string };

export function displayParts(name: string): DisplayParts {
  const m = name.match(/^(\d[\d-]*)_(.*)/);
  if (m) {
    return { number: m[1].replace(/-/g, "."), label: m[2].replace(/_/g, " ") };
  }
  return { number: "", label: name.replace(/_/g, " ") };
}

export function sortKey(name: string): number[] {
  const prefix = name.split("_")[0];
  const parts = prefix.split("-");
  const result: number[] = [];
  for (const p of parts) {
    const n = parseInt(p, 10);
    if (Number.isNaN(n)) return [0];
    result.push(n);
  }
  return result;
}
