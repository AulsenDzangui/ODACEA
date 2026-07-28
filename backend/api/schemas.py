"""Contrats d'API (Pydantic v2).

Le front envoie du JSON en camelCase ; les champs Python restent en snake_case
grâce à `alias_generator=to_camel` + `populate_by_name`. Les options de
préparation reflètent `prepare_for_llm` / `prepare_for_classement`.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PrepOptions(CamelModel):
    filter_columns: bool = True
    clean_dates: bool = True
    sample_items: bool = True
    sample_items_n: int = 5
    # Inclure les fichiers (Item) dans le CSV d'audit. False = « arborescence
    # seule » : seuls les dossiers (RecordGrp) sont transmis à AUD-001, aucun
    # fichier — prime sur l'échantillonnage. Sans effet sur le classement, qui
    # traite toujours tous les Item (prepare_for_classement).
    include_items: bool = True
    include_description: bool = False
    # Injecter les constats mécaniques (volumétrie, formats) calculés par le
    # moteur comme source faisant autorité dans le prompt d'audit. Cf.
    # core.audit_scan : seuls les comptages exacts sont fournis, jamais l'analyse.
    auto_measures: bool = True
    # Demander au modèle l'« avis de classement » (la « Démarche de l'IA ») avant
    # le CSV au classement. Désactiver retire le bloc d'instruction du prompt
    # CLA-001 (cf. prompts.CLA_001.build_system_prompt) — gain de tokens de sortie.
    classement_avis: bool = True
    # Méthode d'identifiant au classement (cf. prompts.CLA_001) :
    #   False (défaut) = « Path » historique : le modèle recopie le chemin complet
    #     en sortie (ancrage fort, meilleure finesse, mais sortie plus longue) ;
    #   True = « Ref » optimisé : le modèle ne recopie qu'un entier court
    #     (sortie courte/rapide, ancrage moindre). Réhydraté côté Python.
    classement_ref: bool = False

    @property
    def effective_sample_n(self) -> int:
        return self.sample_items_n if self.sample_items else 0


class ModelConfig(CamelModel):
    """Configuration LLM commune (dispatch par préfixe de modèle)."""
    model: str
    api_key: str | None = None
    base_url: str | None = None


class ParseRequest(CamelModel):
    csv: str
    prep: PrepOptions = Field(default_factory=PrepOptions)
    batch_size: int = 0
    # Modèle (et éventuel base_url) optionnels : quand le front les fournit, la
    # réponse joint au `tokenEstimate` un **coût d'entrée indicatif €** pour
    # les modèles cloud connus. Absents (ou modèle local/inconnu) → aucun coût.
    model: str | None = None
    base_url: str | None = None


class ParseFromFolderRequest(CamelModel):
    """Import direct d'un dossier local — POST /parse/from-folder.

    **Backend local uniquement** (refusé en démo, comme `enrich`) : le serveur
    scanne l'arborescence réelle sous `source_root` (chemin **sur la machine de
    l'archiviste**) pour en dériver le CSV canonique, puis renvoie la même réponse
    que `/parse` **plus** le CSV dérivé (`derivedCsv`) et les stats du scan
    (`scan`). Le front ne transmet qu'un chemin ; **aucun binaire n'est
    ouvert** (métadonnées seules). `model`/`base_url` optionnels → coût €
    indicatif, comme /parse.
    """
    source_root: str
    prep: PrepOptions = Field(default_factory=PrepOptions)
    batch_size: int = 0
    model: str | None = None
    base_url: str | None = None


class ApplyPreviewRequest(CamelModel):
    """Aperçu avant écriture de l'application physique du classement — POST
    /apply/preview. **Backend local uniquement**. `rows` = lignes du CSV RESIP
    produit (même forme que `resip.rows` de finalize) ; `source_root` = racine du
    fonds (pour tester l'existence des binaires). `target_root`/`resume`
    optionnels → contrôle des garde-fous du répertoire cible dès l'aperçu.
    **Aucun fichier n'est copié** : seule l'existence des sources est testée."""
    rows: list[dict] = Field(default_factory=list)
    source_root: str
    target_root: str = ""
    resume: bool = False


class ApplyRequest(CamelModel):
    """Application physique du classement — POST /apply (SSE). **Backend local
    uniquement**. Copie chaque fichier vers `target_root` selon les lignes RESIP
    (`rows`) ; la **source n'est jamais mutée**. `confirm=True` exigé (l'écriture
    n'a lieu qu'après confirmation explicite) ; `resume` autorise un répertoire
    cible déjà peuplé (reprise idempotente)."""
    rows: list[dict] = Field(default_factory=list)
    source_root: str
    target_root: str
    resume: bool = False
    confirm: bool = False


class AuditRequest(ModelConfig):
    csv: str
    observation: str = ""
    prep: PrepOptions = Field(default_factory=PrepOptions)
    # Mode « plan seul » : ne demande que le plan de classement (Partie 2),
    # sans état des lieux ni notes.
    brief: bool = False
    # Plan de classement de référence injecté comme contrainte dans
    # l'audit (cf. core.reference_plans). `reference_plan` est un bloc
    # d'arborescence dérivé du CSV Resip « dossiers seuls » importé par
    # l'archiviste (POST /reference-plan/from-csv). Le mode (« inspire » /
    # « conform ») règle le registre de la contrainte.
    reference_plan: str = ""
    reference_mode: str = "inspire"


class ReferencePlanFromCsvRequest(CamelModel):
    """CSV Resip « dossiers seuls » à convertir en plan de classement de
    référence — POST /reference-plan/from-csv."""
    csv: str


class PlanFromFileRequest(CamelModel):
    """Plan fourni par l'archiviste à adopter **sans appel LLM** — POST
    /plan/from-file. `content` = texte du fichier importé (CSV Resip « dossiers
    seuls » ou Markdown à bloc arborescence canonique) ; `name` sert au routage
    par extension. Le front ne fait que transporter le texte."""
    name: str = ""
    content: str


class PlanMaterializeRequest(CamelModel):
    """Matérialise le plan courant en dossiers vides réels — POST
    /plan/materialize. **Backend local uniquement** (refusé en démo, comme
    `enrich`). `work_dir` = répertoire de travail **sur la machine de l'archiviste**.
    `clear` **vide d'abord** le répertoire (contenu uniquement) ; il n'est honoré
    qu'avec `confirm=True` (garde-fou : vidage sur action explicite confirmée)."""
    plan_valide: str
    work_dir: str
    clear: bool = False
    confirm: bool = False


class PlanFromFolderRequest(CamelModel):
    """Re-scanne un répertoire de travail réorganisé dans l'Explorateur et
    reconstruit le plan canonique — POST /plan/from-folder. **Backend local
    uniquement**. `current_plan` (optionnel) sert à calculer l'**aperçu des
    changements** (ajouts/suppressions/déplacements/renommages) avant adoption."""
    work_dir: str
    current_plan: str = ""


class ClassementPrepareRequest(CamelModel):
    """Renvoie les items à classer (pour piloter le découpage en lots côté front)."""
    csv: str
    prep: PrepOptions = Field(default_factory=PrepOptions)


class CorrectionExample(CamelModel):
    """Une correction validée réinjectée comme exemple few-shot.
    **Métadonnées seules** : chemin source, dossier cible, nouveau nom."""
    path: str
    target_folder: str
    new_title: str = ""


class ClassementDirective(CamelModel):
    """Une consigne de classement de l'archiviste. **Métadonnées seules**
    (texte rédigé par l'archiviste + éventuel dossier visé) : jamais de contenu
    documentaire. `folder` = nom technique d'un dossier du plan (consigne ancrée)
    ou vide/None (consigne au niveau du fonds). `allow_creation` autorise le
    classement à créer des sous-dossiers sous le dossier visé."""
    text: str
    folder: str | None = None
    allow_creation: bool = False


class ClassementBatchRequest(ModelConfig):
    """Classe un lot : le serveur re-dérive les items et traite la tranche
    [batch_index*batch_size : +batch_size]. batch_size=0 ⇒ tous les items."""
    csv: str
    plan_valide: str
    prep: PrepOptions = Field(default_factory=PrepOptions)
    batch_index: int = 0
    batch_size: int = 0
    # Apprentissage des corrections : corrections validées du même
    # fonds, réinjectées comme exemples few-shot dans CLA-001 (« appliquer la
    # même logique »). Vide ⇒ prompt inchangé. ⚠️ Few-shot = modification de
    # prompt : efficacité à valider sur modèles réels (cf. core.corrections).
    corrections: list[CorrectionExample] = Field(default_factory=list)
    # Consignes de classement de l'archiviste : préconisations ancrées à
    # un dossier du plan ou au niveau du fonds, injectées dans CLA-001. Vide ⇒
    # prompt inchangé. ⚠️ = modification de prompt (cf. core.cla_directives).
    directives: list[ClassementDirective] = Field(default_factory=list)


class ClassementFinalizeRequest(CamelModel):
    """Convertit les lignes LLM accumulées en CSV RESIP (passe unique).

    `directives` : les mêmes consignes que celles envoyées aux lots — au
    finalize, seules celles **autorisant la création** de sous-dossiers importent
    (elles déterminent `allowed_parents` : sous quels dossiers du plan un
    `TargetFolder` en chemin `parent/enfant` est une création légitime plutôt qu'un
    hors-plan). Vide ⇒ conversion inchangée."""
    csv: str
    plan_valide: str
    llm_rows: list[dict]
    directives: list[ClassementDirective] = Field(default_factory=list)
    # Option d'export : retirer le préfixe de position ('1-1_') des noms techniques
    # de dossier (colonne File des RecordGrp) → CSV, manifeste et copie physique
    # cohérents. Défaut off (les numéros ordonnent le fonds). Cf.
    # csv_handler.strip_folder_numbers.
    strip_folder_numbers: bool = False


class ExtractPlansRequest(CamelModel):
    """Re-extrait plan/notes/arbre d'un rapport d'audit déjà obtenu (sans LLM)."""
    report: str


class EnrichRequest(CamelModel):
    """Étape 0 facultative `enrich` exposée au front.

    **Backend local uniquement** : le serveur lit les binaires sous `source_root`
    (chemin sur la machine de l'archiviste) pour en extraire des métadonnées
    et/ou calculer une empreinte SHA-256. Refusé en mode démonstration (le front
    fournirait un chemin qui n'existe pas sur le serveur hébergé, et exposer le
    système de fichiers serait une faille). Renvoie le CSV enrichi (le backend
    reste sans état : aucun fichier écrit côté serveur).
    """
    csv: str
    source_root: str
    overwrite: bool = False
    max_chars: int = 300
    # Calculer l'empreinte SHA-256 des binaires (doublons stricts) en plus
    # de la description. `fingerprint_only` : empreintes seules, sans extraction
    # de texte (toutes extensions hachées).
    fingerprint: bool = False
    fingerprint_only: bool = False


class JournalRequest(CamelModel):
    """Journal de traitement — traçabilité réglementaire, **rendu local**.

    Le front renvoie les métadonnées du traitement déjà obtenues (modèle,
    versions de prompt, durée, anomalies, conformité — issues des `done`/finalize
    SSE) ; le moteur (`core.journal`) en produit un document de traçabilité
    horodaté (`{markdown, journal}`). Aucun contenu documentaire n'y figure :
    `input_name` est un nom de fichier, jamais des données. Le rendu vit côté
    moteur (source unique) — le front ne fait que le présenter/télécharger.
    """
    command: str = "run"
    input_name: str = ""
    model: str | None = None
    # Modèle par agent (`{"AUD-001": …, "CLA-001": …}`) quand l'audit et le
    # classement ont été exécutés par des modèles distincts ; fait foi sur le
    # champ `model` unique quand renseigné.
    models: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None
    rows: int | None = None
    usage: dict | None = None
    resumed: bool = False
    ok: bool = True
    exit_code: int = 0
    warnings: list[str] = Field(default_factory=list)
    conformity: dict | None = None
    description_sent: bool = False
    # Origine du plan de classement : "audit_llm" (issu d'AUD-001) ou "fourni"
    # (fourni par l'archiviste, bypass de l'audit). `plan_modified` = retouché à la
    # main. None = non renseigné (rétro-compat) → ligne omise du journal.
    plan_origin: str | None = None
    plan_modified: bool = False


class ManifestRequest(CamelModel):
    """Manifeste d'arborescence modèle — **rendu local**.

    Le front renvoie les **lignes du CSV RESIP** déjà produites (`rows`, la même
    forme que `resip.rows` de `/classement/finalize`) ; le moteur
    (`core.export_manifest`) en dérive l'arborescence de répertoires cible
    (`{markdown, manifest}`). Aucun contenu documentaire n'y figure (noms de
    dossiers, titres et dates seuls). Le rendu vit côté moteur (source unique) —
    le front ne fait que le présenter/télécharger.
    """
    rows: list[dict] = Field(default_factory=list)


class PlanCompareRequest(CamelModel):
    """Comparaison structurelle de N variantes de plan — **rendu local**.

    Le front lance AUD-001 plusieurs fois (chaque exécution produit une variante
    de plan ; c'est la stochasticité du modèle qui les différencie), puis renvoie
    les textes du bloc « Arborescence technique » obtenus (`plans`) ; le moteur
    (`core.plan_compare`) les compare de façon déterministe — forme de chaque arbre
    et croisement des dossiers (communs/propres) → `{variants, comparison,
    markdown}`. Métadonnées seules (noms de dossiers) ; aucun appel LLM ; rendu
    côté moteur (source unique) — le front ne fait que présenter/choisir.
    """
    plans: list[str] = Field(default_factory=list)


class AgtSessionRequest(CamelModel):
    """Crée une session d'exploration de vrac depuis un CSV.

    **Dérogation au « backend sans état »** : la session (DataFrame +
    historique compact) vit en mémoire process avec TTL — cache de travail
    reconstructible depuis le projet client (le front renvoie ce même CSV
    pour recréer une session expirée), jamais la seule copie.

    `audit_report` (optionnel, 0.6.0) : le rapport d'audit du projet (AUD-001),
    injecté en contexte du system prompt de l'agent quand il est fourni. Absent
    ⇒ exploration « à froid » (prompt inchangé). Le front l'envoie selon un
    toggle (ON par défaut quand un rapport existe) ; le changer recrée la session.
    """
    csv: str
    audit_report: str | None = None


class AgtChatRequest(ModelConfig):
    """Un tour de dialogue avec l'agent (AGT-001).

    `tool_mode` : `auto` (défaut — function calling natif pour un cloud, repli
    JSON contraint pour un serveur local), `native` ou `json` pour forcer.
    """
    session_id: str
    message: str
    tool_mode: str = "auto"


class ValidateConnectionRequest(ModelConfig):
    pass
