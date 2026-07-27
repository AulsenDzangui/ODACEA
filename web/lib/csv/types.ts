export type SedaRow = Record<string, string>;

export type LlmClassementRow = {
  Path: string;
  TargetFolder: string;
  NewTitle: string;
  [key: string]: string;
};

/** Consigne de classement de l'archiviste. **Métadonnées seules** : un texte
 *  rédigé par l'archiviste (+ éventuellement le nom technique d'un dossier du
 *  plan qu'elle vise) — jamais de contenu documentaire. Forme exacte du corps
 *  `directives` de /classement/{batch,finalize} : le moteur en dérive le bloc de
 *  consignes et l'ensemble des dossiers à création autorisée
 *  (`core.cla_directives`) ; le front ne fait que collecter et transporter.
 *  `folder` vide/absent = consigne au niveau du fonds ; `folder` renseigné =
 *  consigne ancrée à ce dossier. `allowCreation` autorise le classement à créer
 *  des sous-dossiers sous le dossier visé. */
export type ClassementDirective = {
  text: string;
  folder?: string;
  allowCreation: boolean;
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
  /** Sous-dossiers créés sous l'autorisation d'une consigne : ni un écart au
   *  plan, ni un hors-plan. Absent des projets persistés avant l'ajout. */
  foldersCreatedAuthorized?: string[];
  /** Rattachement de chaque sous-dossier créé à son dossier parent du plan. */
  foldersCreatedParents?: Record<string, string>;
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
