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
    include_description: bool = False
    # Injecter les constats mécaniques (volumétrie, formats) calculés par le
    # moteur comme source faisant autorité dans le prompt d'audit. Cf.
    # core.audit_scan : seuls les comptages exacts sont fournis, jamais l'analyse.
    auto_measures: bool = True

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


class ParseFromFolderRequest(CamelModel):
    """Import direct d'un dossier local — POST /parse/from-folder.

    **Backend local uniquement** : le serveur scanne l'arborescence réelle sous
    `source_root` (chemin **sur la machine de l'archiviste**) pour en dériver le
    CSV canonique, puis renvoie la même réponse que `/parse` **plus** le CSV
    dérivé (`derivedCsv`) et les stats du scan (`scan`). Le front ne transmet
    qu'un chemin ; **aucun binaire n'est ouvert** (métadonnées seules).
    """
    source_root: str
    prep: PrepOptions = Field(default_factory=PrepOptions)
    batch_size: int = 0


class PlanFromFileRequest(CamelModel):
    """Plan fourni par l'archiviste à adopter **sans appel LLM** — POST
    /plan/from-file. `content` = texte du fichier importé (CSV Resip « dossiers
    seuls » ou Markdown à bloc arborescence canonique) ; `name` sert au routage
    par extension. Le front ne fait que transporter le texte."""
    name: str = ""
    content: str


class PlanFromFolderRequest(CamelModel):
    """Scanne un dossier existant du poste pour en faire un plan — POST
    /plan/from-folder. **Backend local uniquement** : l'arborescence de `work_dir`
    (chemin sur la machine de l'archiviste) devient le plan de classement. Seuls
    les noms de dossiers sont lus ; aucun contenu de fichier n'est ouvert."""
    work_dir: str


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


class ClassementPrepareRequest(CamelModel):
    """Renvoie les items à classer (pour piloter le découpage en lots côté front)."""
    csv: str
    prep: PrepOptions = Field(default_factory=PrepOptions)


class ClassementBatchRequest(ModelConfig):
    """Classe un lot : le serveur re-dérive les items et traite la tranche
    [batch_index*batch_size : +batch_size]. batch_size=0 ⇒ tous les items."""
    csv: str
    plan_valide: str
    prep: PrepOptions = Field(default_factory=PrepOptions)
    batch_index: int = 0
    batch_size: int = 0


class ClassementFinalizeRequest(CamelModel):
    """Convertit les lignes LLM accumulées en CSV RESIP (passe unique)."""
    csv: str
    plan_valide: str
    llm_rows: list[dict]


class ExtractPlansRequest(CamelModel):
    """Re-extrait plan/notes/arbre d'un rapport d'audit déjà obtenu (sans LLM)."""
    report: str


class ValidateConnectionRequest(ModelConfig):
    pass
