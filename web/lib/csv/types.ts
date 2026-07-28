import type { Anomaly } from "./anomalies";

export type SedaRow = Record<string, string>;

// Sortie LLM du classement. `Ref` (identifiant court) remplace `Path` en
// entrée/sortie du modèle : le backend réhydrate `Path` à la conversion RESIP.
// Le front ne fait que transporter ces lignes (opaques) vers /classement/finalize.
// `Path` reste toléré pour les projets persistés avant l'optimisation `Ref`.
export type LlmClassementRow = {
  Ref?: string;
  Path?: string;
  TargetFolder: string;
  NewTitle: string;
  [key: string]: string | undefined;
};

// Correction validée réinjectée comme exemple few-shot (opt-in).
// **Métadonnées seules** : chemin source → dossier cible retenu (+ nom normalisé)
// — jamais de contenu. Forme exacte du corps `corrections` de /classement/batch
// (le moteur en dérive le bloc few-shot, cf. `core.corrections`). Le front ne
// fait que collecter ces triplets et les transporter — aucune logique métier.
export type CorrectionExample = {
  path: string;
  targetFolder: string;
  newTitle: string;
};

// Consigne de classement de l'archiviste. **Métadonnées seules** : un
// texte rédigé par l'archiviste (+ éventuellement le nom technique d'un dossier
// du plan qu'elle vise) — jamais de contenu documentaire. Forme exacte du corps
// `directives` de /classement/{batch,finalize} (le moteur en dérive le bloc de
// consignes et l'ensemble des dossiers à création autorisée, cf.
// `core.cla_directives`). Le front ne fait que collecter et transporter.
// `folder` vide/absent = consigne au niveau du fonds ; `folder` renseigné =
// consigne ancrée à ce dossier. `allowCreation` autorise le classement à créer
// des sous-dossiers sous le dossier visé.
export type ClassementDirective = {
  text: string;
  folder?: string;
  allowCreation: boolean;
};

export type SimplifiedItem = {
  Ref: string;
  Path: string; // chemin physique (aperçu/réhydratation), non envoyé au LLM
  CurrentTitle: string;
  Date: string;
  Description?: string; // Content.Description renommée, transmise au LLM si présente
};

export type FolderTree = Record<string, string | null>;

/** Conformité au plan calculée à la source (backend) — le front l'affiche telle
 *  quelle (cf. `convert_classement_to_resip`). Compare l'arborescence produite par
 *  le classement à celle du plan validé à l'audit (égalité stricte, au niveau
 *  dossier). */
export type ResipStats = {
  /** false quand l'arborescence du plan n'a pas pu être lue (mesure impossible). */
  planParsed: boolean;
  planFolders: number;
  outputFolders: number;
  /** Dossiers créés par le classement mais absents du plan validé. */
  foldersOffPlan: string[];
  /** Dossiers présents au plan mais restés sans contenu. */
  foldersMissing: string[];
  /** Items dont la cible LLM ressemblait à un fichier (extension) au lieu d'un
   *  dossier : rattachés à la racine au lieu de créer un dossier-poubelle. */
  itemsMalformed: number;
  /** true ssi le plan a été lu ET aucun écart dans les deux sens. */
  planMatches: boolean;
  // ── Compteurs de qualité, calculés à la source par le moteur ───────────────
  // Le front les affiche tels quels — jamais re-dérivés des messages texte.
  // Optionnels : absents des projets persistés avant l'introduction des
  // compteurs de qualité (les lectures appliquent un défaut `?? 0`).
  /** Items du CSV source à classer. */
  itemsTotal?: number;
  /** Items effectivement rattachés à un dossier du plan. */
  itemsClassified?: number;
  /** Items absents de la sortie LLM (jamais classés). */
  itemsUnclassified?: number;
  /** NewTitle dont l'extension a été réalignée sur celle du Path d'origine. */
  extensionsFixed?: number;
  /** Items à TargetFolder inconnu (ni dans le plan, ni malformé). */
  targetsUnknown?: number;
  /** Path renvoyés par le LLM introuvables dans le CSV original. */
  pathsNotFound?: number;
  /** Mode Ref uniquement : identifiants Ref hallucinés non résolus. */
  refsUnresolved?: number;
  // ── sous-dossiers créés sous autorisation d'une consigne ───────────────────
  /** Sous-dossiers créés par le classement sous une consigne autorisant la
   *  création (rattachés au bon parent, exclus de `foldersOffPlan`/`planMatches`). */
  foldersCreatedAuthorized?: string[];
  /** Rattachement des sous-dossiers créés : nom du sous-dossier → dossier parent. */
  foldersCreatedParents?: Record<string, string>;
};

export type ResipResult = {
  rows: SedaRow[];
  columns: string[];
  warnings: string[];
  /** Anomalies typées pour le triage — catégorisées par le moteur
   *  (`/classement/finalize` → `resip.anomalies`). Optionnel : absent des
   *  projets persistés avant son introduction (repli `anomaliesFromWarnings`). */
  anomalies?: Anomaly[];
  /** Optionnel : absent des projets persistés avant l'ajout des stats. */
  stats?: ResipStats;
};

/** Résumé persisté d'un lot de classement (mode traitement par lot). */
export type ClassementBatch = {
  itemCount: number;
  rows: LlmClassementRow[];
  /** Avis de classement propre à ce lot (prose avant le bloc CSV de sa réponse).
   *  Stocké par lot pour un affichage distinct — sinon les avis se concatènent
   *  en un seul bloc illisible. Absent des projets sauvegardés avant cet ajout. */
  preCsv?: string;
  /** Issue du lot. Les lots sont persistés **au fil de l'eau** (dès qu'un lot
   *  s'achève, pas seulement à la finalisation) : sans ce champ, un classement
   *  rouvert après interruption serait indiscernable d'un classement complet.
   *  Absent des projets sauvegardés avant cet ajout → lu comme `"done"`. */
  status?: "done" | "error";
  /** Message d'erreur du lot, quand `status === "error"`. */
  error?: string;
};
