import {
  parsePlanTree,
  parsePlanEntries,
  displayParts,
  stripFondsLabel,
} from "./plan-tree";

// ── Éditeur structuré du plan ──────────────────────────────────────────────
// Modèle d'arbre éditable + sérialisation vers le bloc « Arborescence
// technique » canonique du gabarit AUD-001. Les préfixes numériques des noms
// techniques (1_, 1-1_, …) sont RECALCULÉS depuis la position de chaque nœud à
// chaque sérialisation : l'utilisateur n'édite que le titre descriptif et le
// nom technique « nu » (slug). Le résultat reste parsable à l'identique par
// `parse_plan_tree` (Python, autoritatif) et par sa copie miroir
// `plan-tree.ts::parsePlanTree`.

export type PlanNode = {
  /** Titre descriptif (« Restauration scolaire »). */
  title: string;
  /** Nom technique sans préfixe numérique (« Cantine ») — le préfixe est
   *  recalculé à la sérialisation depuis la position du nœud. */
  slug: string;
  children: PlanNode[];
};

export type PlanModel = {
  /** Intitulé du fonds (ligne « Fonds — … → racine/ »). */
  rootTitle: string;
  /** Nom technique de la racine : `Dossier_racine` (placeholder mappé au nœud
   *  File="." côté Python) ou racine organisationnelle réelle (ex.
   *  `AFFAIRES_SCOLAIRES`, reparentée par parse_plan_tree). */
  rootSlug: string;
  nodes: PlanNode[];
};

export const ROOT_PLACEHOLDER = "Dossier_racine";

const NUMERIC_PREFIX_RE = /^\d+(?:-\d+)*_/;

/** Nom technique « nu » : préfixe numérique retiré s'il existe. */
function stripNumericPrefix(name: string): string {
  return name.replace(NUMERIC_PREFIX_RE, "");
}

/** Nom technique dérivé d'un titre descriptif (accents retirés, espaces → _). */
export function slugify(title: string): string {
  const s = title
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^A-Za-z0-9]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
  return s || "Nouveau_dossier";
}

/**
 * Construit le modèle éditable depuis le texte du plan. Les relations
 * parent/enfant viennent de `parsePlanTree` (mêmes règles que le Python) ;
 * l'ordre des frères et les titres viennent de `parsePlanEntries` (ordre du
 * document). Retourne `null` si aucune arborescence n'est lisible — l'appelant
 * retombe alors sur l'édition texte.
 */
export function parsePlanModel(planValide: string): PlanModel | null {
  const entries = parsePlanEntries(planValide);
  if (entries.length === 0) return null;

  const tree = parsePlanTree(planValide); // {name: parent | null}, racine exclue

  let rootTitle = "";
  let rootSlug = ROOT_PLACEHOLDER;
  const rootEntry = entries.find((e) => e.name === ROOT_PLACEHOLDER);
  if (rootEntry) {
    // Le label « Fonds — » est ré-ajouté à la sérialisation : on le retire ici
    // pour qu'il ne s'accumule pas dans le modèle édité.
    rootTitle = stripFondsLabel(rootEntry.title);
  } else {
    // Racine organisationnelle réelle : seule racine de l'arbre, préfixe
    // non numérique de plus d'un caractère (cf. reparentage parsePlanTree).
    const roots = Object.keys(tree).filter((n) => tree[n] === null);
    const main = roots.find(
      (n) => !/^\d/.test(n.split("_")[0]) && n.split("_")[0].length > 1,
    );
    if (main && roots.length === 1) {
      rootSlug = main;
      rootTitle =
        entries.find((e) => e.name === main)?.title || displayParts(main).label;
    }
  }

  const byName = new Map<string, PlanNode>();
  const model: PlanModel = { rootTitle, rootSlug, nodes: [] };

  for (const { name, title } of entries) {
    if (name === ROOT_PLACEHOLDER || name === rootSlug) continue;
    if (!(name in tree) || byName.has(name)) continue;
    const node: PlanNode = {
      title: title || displayParts(name).label,
      slug: stripNumericPrefix(name),
      children: [],
    };
    byName.set(name, node);
    const parent = tree[name];
    const parentNode =
      parent !== null && parent !== rootSlug ? byName.get(parent) : undefined;
    // Parent introuvable (préfixe orphelin) : rattaché au premier niveau,
    // comme le fera la conversion Python.
    (parentNode ? parentNode.children : model.nodes).push(node);
  }

  if (model.nodes.length === 0 && rootSlug === ROOT_PLACEHOLDER) return null;
  return model;
}

/** Nom technique complet d'un nœud à sa position : `1-2_Slug`. */
export function technicalName(numberParts: number[], slug: string): string {
  return `${numberParts.join("-")}_${slug}`;
}

/** Titres sans flèche : « → » casserait le découpage titre/nom technique. */
function safeTitle(title: string): string {
  return title.replace(/\s*(?:→|->)\s*/g, " - ").trim();
}

/** Contenu du bloc ```text``` : l'arbre dessiné, préfixes recalculés. */
export function serializePlanTreeText(model: PlanModel): string {
  const lines: string[] = [
    `Fonds — ${safeTitle(model.rootTitle) || "[Nom du fonds]"} → ${model.rootSlug}/`,
  ];

  const renderNode = (
    node: PlanNode,
    numberParts: number[],
    indent: string,
    isLast: boolean,
  ) => {
    const number = `${numberParts.join(".")}.`;
    const tech = technicalName(numberParts, node.slug);
    lines.push(
      `${indent}${isLast ? "└──" : "├──"} ${number} ${safeTitle(node.title)} → ${tech}/`,
    );
    const childIndent = indent + (isLast ? "      " : "│     ");
    node.children.forEach((child, i) =>
      renderNode(
        child,
        [...numberParts, i + 1],
        childIndent,
        i === node.children.length - 1,
      ),
    );
  };

  model.nodes.forEach((node, i) => {
    lines.push("  │"); // séparateur visuel entre groupes de premier niveau
    renderNode(node, [i + 1], "  ", i === model.nodes.length - 1);
  });

  return lines.join("\n");
}

/** Localise un nœud par son nom technique complet (préfixe inclus) et renvoie
 *  ses indices 1-based dans l'arbre — base du recalcul de préfixe d'un enfant. */
function findNodeByTech(
  nodes: PlanNode[],
  parentTech: string,
  prefix: number[] = [],
): { node: PlanNode; numberParts: number[] } | null {
  for (let i = 0; i < nodes.length; i++) {
    const parts = [...prefix, i + 1];
    if (technicalName(parts, nodes[i].slug) === parentTech)
      return { node: nodes[i], numberParts: parts };
    const found = findNodeByTech(nodes[i].children, parentTech, parts);
    if (found) return found;
  }
  return null;
}

/**
 * Ajoute un dossier au plan sous le parent désigné (`parentTech` = nom technique
 * complet, ex. `1-2_Allergies`) ou au premier niveau si `parentTech` est `null`,
 * et renvoie le plan régénéré + le nom technique complet du nouveau dossier (son
 * préfixe numérique est recalculé depuis sa position, comme partout ailleurs).
 *
 * Réutilise le modèle structuré de l'éditeur d'arborescence : le résultat
 * reste parsable à l'identique par `parse_plan_tree` (Python autoritatif). Sert
 * au rattrapage des non-classés, où l'archiviste crée le dossier manquant
 * qui a fait échouer le classement (le LLM ne peut viser qu'un dossier du plan).
 * Retourne `null` si l'arborescence est illisible ou le parent introuvable.
 */
export function addFolderToPlan(
  planValide: string,
  parentTech: string | null,
  title: string,
): { plan: string; tech: string } | null {
  const model = parsePlanModel(planValide);
  if (!model) return null;
  const child: PlanNode = {
    title: title.trim(),
    slug: slugify(title),
    children: [],
  };
  let numberParts: number[];
  if (parentTech === null) {
    model.nodes.push(child);
    numberParts = [model.nodes.length];
  } else {
    const found = findNodeByTech(model.nodes, parentTech);
    if (!found) return null;
    found.node.children.push(child);
    numberParts = [...found.numberParts, found.node.children.length];
  }
  return {
    plan: applyPlanModel(planValide, model),
    tech: technicalName(numberParts, child.slug),
  };
}

/** Recense le nom technique de chaque nœud par identité d'objet (`PlanNode →
 *  tech`). Base du remap après une mutation : on compare la table avant/après en
 *  s'appuyant sur l'identité des nœuds (le préfixe, lui, dépend de la position). */
function collectTechs(
  nodes: PlanNode[],
  prefix: number[],
  acc: Map<PlanNode, string>,
): Map<PlanNode, string> {
  nodes.forEach((node, i) => {
    const parts = [...prefix, i + 1];
    acc.set(node, technicalName(parts, node.slug));
    collectTechs(node.children, parts, acc);
  });
  return acc;
}

/** Localise un nœud par son nom technique complet et renvoie ses frères + indice. */
function locateByTech(
  nodes: PlanNode[],
  tech: string,
  prefix: number[] = [],
): { siblings: PlanNode[]; index: number; node: PlanNode } | null {
  for (let i = 0; i < nodes.length; i++) {
    const parts = [...prefix, i + 1];
    if (technicalName(parts, nodes[i].slug) === tech)
      return { siblings: nodes, index: i, node: nodes[i] };
    const found = locateByTech(nodes[i].children, tech, parts);
    if (found) return found;
  }
  return null;
}

/** Résultat d'un renommage : plan régénéré, nouveau nom technique du dossier, et
 *  remap (ancien → nouveau) à appliquer aux affectations qui le visaient. */
export type FolderRename = {
  plan: string;
  tech: string;
  remap: Map<string, string>;
};

/** Résultat d'une suppression : plan régénéré, remap des dossiers décalés, et
 *  noms techniques effectivement supprimés (dossier + sous-arbre). */
export type FolderDelete = {
  plan: string;
  remap: Map<string, string>;
  removed: string[];
};

/**
 * Renomme un dossier du plan (titre + nom technique « nu »). La position est
 * inchangée, donc seul le slug de ce dossier change : le remap ne contient que
 * `{ancienTech → nouveauTech}`. Retourne `null` si l'arborescence est illisible
 * ou le dossier introuvable. Pendant pur de `addFolderToPlan`.
 */
export function renameFolderInPlan(
  planValide: string,
  tech: string,
  newTitle: string,
): FolderRename | null {
  const model = parsePlanModel(planValide);
  if (!model) return null;
  const loc = locateByTech(model.nodes, tech);
  if (!loc) return null;
  loc.node.title = newTitle.trim();
  loc.node.slug = slugify(newTitle);
  const newTech = collectTechs(model.nodes, [], new Map()).get(loc.node)!;
  return {
    plan: applyPlanModel(planValide, model),
    tech: newTech,
    remap: new Map([[tech, newTech]]),
  };
}

/**
 * Supprime un dossier du plan (avec son sous-arbre). Les frères suivants voient
 * leur préfixe recalculé : le remap réaligne ces dossiers décalés, et `removed`
 * liste les noms techniques disparus (à dé-affecter côté appelant). Retourne
 * `null` si l'arborescence est illisible ou le dossier introuvable.
 */
export function deleteFolderFromPlan(
  planValide: string,
  tech: string,
): FolderDelete | null {
  const model = parsePlanModel(planValide);
  if (!model) return null;
  const before = collectTechs(model.nodes, [], new Map());
  const loc = locateByTech(model.nodes, tech);
  if (!loc) return null;

  // Sous-arbre supprimé (dossier visé + tous ses descendants), par identité.
  const removedNodes = new Set<PlanNode>();
  const gather = (n: PlanNode) => {
    removedNodes.add(n);
    n.children.forEach(gather);
  };
  gather(loc.node);
  const removed = [...removedNodes].map((n) => before.get(n)!);

  loc.siblings.splice(loc.index, 1);

  const after = collectTechs(model.nodes, [], new Map());
  const remap = new Map<string, string>();
  for (const [node, oldTech] of before) {
    if (removedNodes.has(node)) continue;
    const newTech = after.get(node);
    if (newTech && newTech !== oldTech) remap.set(oldTech, newTech);
  }

  return { plan: applyPlanModel(planValide, model), remap, removed };
}

// ── Déplacement d'un nœud (glisser-déposer) ──────────────────────────────────
// Réorganisation libre de l'arbre : un dossier peut devenir frère (avant/après)
// d'un autre ou son sous-dossier (`inside`), à n'importe quel niveau. Les
// préfixes numériques sont recalculés à la sérialisation, donc le déplacement
// n'a qu'à réagencer les nœuds. Opère par identité d'objet (les indices bougent
// après détachement), comme collectTechs/locateByTech mais sans nom technique.

/** Position d'un dépôt relativement au nœud cible. */
export type DropPosition = "before" | "after" | "inside";

/** Chemin d'un nœud : indices (0-based) successifs depuis model.nodes. */
type NodePath = number[];

function nodeAtPath(nodes: PlanNode[], path: NodePath): PlanNode | null {
  let list = nodes;
  let node: PlanNode | undefined;
  for (const idx of path) {
    node = list[idx];
    if (!node) return null;
    list = node.children;
  }
  return node ?? null;
}

/** Vrai si `node` est `ancestor` lui-même ou l'un de ses descendants. */
function isSelfOrDescendant(ancestor: PlanNode, node: PlanNode): boolean {
  if (ancestor === node) return true;
  return ancestor.children.some((c) => isSelfOrDescendant(c, node));
}

/** Localise un nœud par identité et renvoie ses frères + son indice. */
function locateByIdentity(
  nodes: PlanNode[],
  node: PlanNode,
): { siblings: PlanNode[]; index: number } | null {
  for (let i = 0; i < nodes.length; i++) {
    if (nodes[i] === node) return { siblings: nodes, index: i };
    const found = locateByIdentity(nodes[i].children, node);
    if (found) return found;
  }
  return null;
}

/**
 * Déplace le nœud `sourcePath` relativement au nœud `targetPath` : frère avant/
 * après (`before`/`after`) ou dernier enfant (`inside`). Renvoie un nouveau
 * modèle (l'entrée n'est pas mutée) ou `null` si un chemin est introuvable, si
 * source = cible, ou si la cible est un descendant de la source (déplacement qui
 * corromprait l'arbre). Les préfixes numériques sont recalculés à la
 * sérialisation — rien à renuméroter ici.
 */
export function moveNodeInModel(
  model: PlanModel,
  sourcePath: NodePath,
  targetPath: NodePath,
  position: DropPosition,
): PlanModel | null {
  const next = structuredClone(model);
  const source = nodeAtPath(next.nodes, sourcePath);
  const target = nodeAtPath(next.nodes, targetPath);
  if (!source || !target || source === target) return null;
  // Interdit : déposer un dossier dans son propre sous-arbre.
  if (isSelfOrDescendant(source, target)) return null;

  // Détacher la source (référence conservée pour la ré-insertion par identité).
  const from = locateByIdentity(next.nodes, source);
  if (!from) return null;
  from.siblings.splice(from.index, 1);

  if (position === "inside") {
    target.children.push(source);
  } else {
    // Ré-localiser la cible après détachement (ses indices ont pu bouger).
    const to = locateByIdentity(next.nodes, target);
    if (!to) return null;
    to.siblings.splice(position === "after" ? to.index + 1 : to.index, 0, source);
  }
  return next;
}

const BLOCK_HEADER =
  "**Arborescence technique** *(chaque dossier porte son titre descriptif puis son nom technique, séparés par « → » ; dossiers uniquement, jamais de fichiers individuels)* **:**";

/** Bloc complet : en-tête du gabarit + fence ```text```. */
export function serializePlanBlock(model: PlanModel): string {
  return `${BLOCK_HEADER}\n\n\`\`\`text\n${serializePlanTreeText(model)}\n\`\`\``;
}

const MARKERS_RE =
  /(<!--\s*PLAN_STRUCTURE_START\s*-->)([\s\S]*?)(<!--\s*PLAN_STRUCTURE_END\s*-->)/;
const HEADER_RE = /[Aa]rborescence\s+technique/;

/** Une ligne de dossier de l'arborescence (« titre → nom_technique/ »). */
function isFolderLine(line: string): boolean {
  const seg = line.split(/\s*(?:→|->)\s*/);
  return /([\w][\w-]*)\//.test(seg[seg.length - 1]);
}

/** Ligne purement décorative de l'arbre (│, ├, espaces) ou fence. */
function isTreeFiller(line: string): boolean {
  return /^[│├└─\s]*$/.test(line) || /^\s*```/.test(line.trim());
}

/**
 * Réinjecte le bloc arborescence régénéré dans le texte du plan, sans toucher
 * au reste (« Plan retenu », « Approche retenue », préconisations…). Trois
 * stratégies, par fiabilité décroissante — miroir des replis de lecture :
 * 1. balises `<!-- PLAN_STRUCTURE_START/END -->` (gabarit) ;
 * 2. en-tête « Arborescence technique » suivi d'un fence ``` ;
 * 3. plage contiguë de lignes de dossiers (plan collé à la main).
 */
export function applyPlanModel(planValide: string, model: PlanModel): string {
  const block = serializePlanBlock(model);

  const m = planValide.match(MARKERS_RE);
  if (m) {
    return planValide.replace(MARKERS_RE, `$1\n${block}\n$3`);
  }

  const header = planValide.match(HEADER_RE);
  if (header && header.index !== undefined) {
    // Début de la ligne portant l'en-tête.
    const lineStart = planValide.lastIndexOf("\n", header.index) + 1;
    const after = planValide.slice(header.index);
    const fenceOpen = after.match(/```[a-z]*\n/);
    if (fenceOpen && fenceOpen.index !== undefined) {
      const fenceCloseIdx = after.indexOf(
        "```",
        fenceOpen.index + fenceOpen[0].length,
      );
      if (fenceCloseIdx >= 0) {
        const end = header.index + fenceCloseIdx + 3;
        return planValide.slice(0, lineStart) + block + planValide.slice(end);
      }
    }
  }

  // Plage contiguë de lignes de dossiers (lignes décoratives tolérées entre
  // elles), en-tête inclus s'il précède immédiatement.
  const lines = planValide.split("\n");
  let first = -1;
  let last = -1;
  for (let i = 0; i < lines.length; i++) {
    if (isFolderLine(lines[i])) {
      if (first === -1) first = i;
      last = i;
    } else if (first !== -1 && !isTreeFiller(lines[i])) {
      break; // fin de la plage contiguë
    }
  }
  if (first === -1) {
    // Aucune arborescence existante : bloc ajouté en fin de plan.
    return `${planValide.trimEnd()}\n\n${block}\n`;
  }
  return [...lines.slice(0, first), block, ...lines.slice(last + 1)].join("\n");
}

// ── Validation live du plan ──────────────────────────────────────────────────
// Deux entrées : le modèle de l'éditeur structuré (problèmes rattachés au nom
// technique du nœud, pour affichage inline) et le texte brut du plan (édition
// Markdown manuelle). Non bloquante : on signale, l'utilisateur tranche.

export type PlanIssue = {
  /** Nom technique complet du dossier concerné ("" = problème global/racine). */
  tech: string;
  message: string;
};

// Nom technique sûr : ASCII sans accent — le parsing Python accepte l'unicode
// mais un nom de dossier portable (FS, miroir TS) reste en [A-Za-z0-9_-].
const SAFE_SLUG_RE = /^[A-Za-z0-9][A-Za-z0-9_-]*$/;

function slugMessage(slug: string): string | null {
  if (!slug.trim()) return "nom technique vide";
  if (!SAFE_SLUG_RE.test(slug))
    return "caractères invalides dans le nom technique (lettres non accentuées, chiffres, « _ » et « - » uniquement, sans espace)";
  return null;
}

export function validatePlanModel(model: PlanModel): PlanIssue[] {
  const issues: PlanIssue[] = [];

  const rootMsg = slugMessage(model.rootSlug);
  if (rootMsg) issues.push({ tech: "", message: `racine : ${rootMsg}` });
  else if (!model.rootSlug.includes("_"))
    issues.push({
      tech: "",
      message:
        "racine : le nom technique doit contenir un « _ » pour être reconnu (ex. Dossier_racine)",
    });
  else if (/^\d/.test(model.rootSlug))
    issues.push({
      tech: "",
      message:
        "racine : un nom commençant par un chiffre serait lu comme un dossier ordinaire",
    });

  const walk = (nodes: PlanNode[], numberPrefix: number[]) => {
    const seen = new Map<string, string>(); // slug minuscule → tech du 1er porteur
    nodes.forEach((node, i) => {
      const parts = [...numberPrefix, i + 1];
      const tech = technicalName(parts, node.slug);
      if (!node.title.trim())
        issues.push({ tech, message: `${tech} : titre descriptif vide` });
      const msg = slugMessage(node.slug);
      if (msg) issues.push({ tech, message: `${tech} : ${msg}` });
      const key = node.slug.trim().toLowerCase();
      if (key) {
        const firstTech = seen.get(key);
        if (firstTech)
          issues.push({
            tech,
            message: `${tech} : doublon de nom avec ${firstTech} au même niveau`,
          });
        else seen.set(key, tech);
      }
      walk(node.children, parts);
    });
  };
  walk(model.nodes, []);

  if (model.nodes.length === 0)
    issues.push({ tech: "", message: "le plan ne contient aucun dossier" });

  return issues;
}

/**
 * Validation du plan en texte (édition Markdown manuelle). Détecte ce que
 * l'éditeur structuré rend impossible : doublons de noms techniques, préfixes
 * numériques incohérents (parent introuvable), noms invalides.
 */
export function validatePlanText(planValide: string): string[] {
  const entries = parsePlanEntries(planValide);
  if (entries.length === 0)
    return [
      "Arborescence technique introuvable : aucune ligne « titre → nom_technique/ » détectée.",
    ];

  const issues: string[] = [];

  // Doublons de nom technique complet (le classement cible par ce nom).
  const counts = new Map<string, number>();
  for (const { name } of entries)
    counts.set(name, (counts.get(name) ?? 0) + 1);
  for (const [name, n] of counts)
    if (n > 1 && name !== ROOT_PLACEHOLDER)
      issues.push(`Doublon : « ${name}/ » apparaît ${n} fois.`);

  // Noms invalides (accents, caractères hors [A-Za-z0-9_-]).
  for (const name of counts.keys()) {
    if (name === ROOT_PLACEHOLDER) continue;
    if (!SAFE_SLUG_RE.test(name))
      issues.push(
        `Nom technique invalide : « ${name}/ » (lettres non accentuées, chiffres, « _ » et « - » uniquement).`,
      );
  }

  // Préfixes incohérents : un préfixe composé (1-2) dont le parent (1) n'existe
  // pas — le dossier serait rattaché à la racine à la conversion.
  const tree = parsePlanTree(planValide);
  for (const name of Object.keys(tree)) {
    const prefix = name.split("_")[0];
    const parts = prefix.split("-");
    if (parts.length < 2 || !/^\d/.test(prefix)) continue;
    const expected = parts.slice(0, -1).join("-");
    const parent = tree[name];
    if (parent === null || parent.split("_")[0] !== expected)
      issues.push(
        `Préfixe incohérent : « ${name}/ » suppose un parent « ${expected}_… » introuvable — il sera rattaché à la racine.`,
      );
  }

  return issues;
}
