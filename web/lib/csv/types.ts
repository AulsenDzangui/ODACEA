export type SedaRow = Record<string, string>;

export type LlmClassementRow = {
  Path: string;
  TargetFolder: string;
  NewTitle: string;
  [key: string]: string;
};

export type SimplifiedItem = {
  Path: string;
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
};

export type ResipResult = {
  rows: SedaRow[];
  columns: string[];
  warnings: string[];
  /** Optionnel : absent des projets persistés avant l'ajout des stats. */
  stats?: ResipStats;
};

/** Résumé persisté d'un lot de classement (mode traitement par lot). */
export type ClassementBatch = {
  itemCount: number;
  rows: LlmClassementRow[];
};
