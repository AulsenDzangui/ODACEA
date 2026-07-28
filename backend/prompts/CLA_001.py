# -----------------------------------------------------------------------------
# Prompt CLA-001 (texte) — © 2026 Aulsen Dzangui — Licence CC BY-SA 4.0
# Le texte de la chaîne SYSTEM_PROMPT ci-dessous est sous CC BY-SA 4.0
# (voir LICENSE-PROMPTS à la racine du dépôt). Le code Python l'entourant
# reste sous AGPL-3.0 (voir LICENSE).
# Origine : https://github.com/AulsenDzangui/bibliotheque-prompts-archivistiques
# -----------------------------------------------------------------------------
# Le prompt existe en deux variantes, pilotées par `ref_mode` (cf.
# build_system_prompt) :
#
#   • ref_mode=False (« Path ») — méthode historique : le modèle reçoit le
#     chemin complet `Path` et le **recopie en sortie** comme identifiant. La
#     recopie ligne à ligne fait office d'ancrage (le modèle « relit » l'arbo
#     source avant de choisir le dossier) → meilleure finesse de classement,
#     mais sortie plus longue (decode séquentiel = plus lent).
#   • ref_mode=True (« Ref ») — méthode optimisée : le modèle reçoit `Ref`
#     (entier court) + `Path` en entrée mais ne recopie que la `Ref` en sortie.
#     Sortie bien plus courte (rapide), au prix d'un ancrage moindre.
#
# Les deux sont des expériences comparables (outil-laboratoire). Le reste du
# prompt (rôle, profondeur, nommage) est invariant.

# Version du prompt : à incrémenter à CHAQUE
# modification du texte du prompt (fragments, build_system_prompt,
# build_user_message). Renvoyée dans les `done{promptVersion}` de l'API et
# consignée dans les rapports d'évaluation (`cli.py eval`).
#
# 1.1.0. canal optionnel d'**exemples de corrections** (few-shot). Le
#   comportement par défaut (sans exemples) est **inchangé** : prompt assemblé
#   byte-identique à la 1.0.0. ⚠️ L'efficacité du few-shot reste à mesurer sur
# modèles réels (/ expérience (a) du `evals/README.md`) avant adoption.
# 1.2.0 — canal optionnel de **notes de connaissance du vrac**
#   (faits validés au fil du dialogue avec l'agent). Retiré en 1.3.0 (l'agent
#   vrac a perdu la capacité de mémoriser des faits).
# 1.3.0 — retrait du canal `knowledge` : l'agent vrac ne produit plus de
#   notes de connaissance (recentré sur l'exploration/recherche seule), plus
#   rien ne l'alimente. Comportement par défaut inchangé (le canal était déjà
#   opt-in et jamais activé en production) ; seul le paramètre disparaît.
# 1.4.0 — canal optionnel de **consignes de classement de l'archiviste**
#   (par dossier du plan ou au niveau du fonds) + convention de sortie autorisant,
#   pour les dossiers désignés, un `TargetFolder` en chemin `dossier/Nouveau_sous_
#   dossier` (création de sous-dossiers). Comportement par défaut (sans consigne)
#   **inchangé** : prompt assemblé byte-identique à la 1.3.0. ⚠️ L'efficacité
# reste à mesurer sur modèles réels (/ métrique `directivesFollowedPct`).
# 1.5.0 — nommage : **suppression du préfixe de date ISO** en tête de NewTitle.
#   Les dates fournies (colonne `Date`, StartDate/EndDate) sont des dates de
#   *modification de fichier*, pas la date du document : en préfixe elles
#   produisaient des noms trompeurs (`2025-02-28_Attestation-fiscale-2019`). Le
#   modèle ne conserve désormais une date que si elle est signifiante et déjà
#   présente dans le nom/contenu d'origine, intégrée au nom sans préfixe technique.
# ⚠️ Modification du comportement de nommage : chiffres avant/après à
#   mesurer via le harnais d'éval (`cli.py eval`).
PROMPT_VERSION = "1.5.0"

_ROLE = """\
# Rôle
Vous êtes un assistant archiviste. Pour chaque fichier de la liste fournie, vous décidez de sa destination dans le plan de classement et de son nouveau nom normalisé."""

# Sections communes aux deux variantes (la règle de profondeur et le nommage
# sont identiques ; le nommage référence `Path`, présent en entrée dans les deux
# modes).
_PROFONDEUR = """\
# Niveau de classement (règle de profondeur)
Classez chaque fichier dans le dossier **le plus profond** qui lui convient.
- Si un sous-dossier correspond au fichier, utilisez ce sous-dossier ; n'utilisez **jamais** son dossier parent à la place.
- N'utilisez un dossier parent que si **aucun** de ses sous-dossiers ne convient (fichier transversal à toute la branche).

Exemple : pour « liste élèves rentrée 2023 », si le plan contient `1-1_Inscriptions_scolaires/` ET son sous-dossier `1-1-2_Rentree_2023-2024/`, alors `TargetFolder` = `1-1-2_Rentree_2023-2024` (le plus précis), et surtout pas `1-1_Inscriptions_scolaires`."""

_NOMMAGE = """\
# Règles de nommage (NewTitle)
- Nom court et parlant, sans répéter le nom du dossier parent.
- Pas d'espace ni de caractère spécial (accents et cédilles inclus). Séparateur : `-` ou `_`.
- **N'ajoutez jamais de date en préfixe.** Les dates fournies (colonne `Date`, StartDate/EndDate) sont des dates de *modification du fichier*, pas la date réelle du document : les placer en tête produit des noms trompeurs (ex. `2025-02-28_Attestation-fiscale-2019`). Ne gardez une année ou une date que si elle est **déjà présente** dans le nom d'origine ou le contenu du document (élément signifiant) et intégrez-la naturellement au nom, sans en faire un préfixe technique (ex. `Attestation-fiscale-2019`).
- Suffixe de version si pertinent : `V01`, `V02`, `VP` (provisoire), `VF` (finale).
- **Préserver l'extension du fichier d'origine** telle qu'elle apparaît dans `Path` (ex. `.docx` reste `.docx`, `.JPG` reste `.JPG`). Ne jamais convertir ni modifier l'extension : un `.docx` ne devient pas `.pdf`, un `.xlsx` ne devient pas `.csv`, etc. Conserver la casse exacte de l'extension d'origine.

**Exemples :** `Bulletin-paie-2019.pdf` ; `Attestation-fiscale-2019.pdf` ; `CR-comite-pilotage_V02.pdf` ; `rapport-activite_VF.docx`"""


# Bloc « Tâche » spécifique à chaque mode (format de sortie + colonne identifiant).
_TACHE_PATH = """\
# Tâche
À partir du plan de classement validé, produisez un CSV à 3 colonnes :

```
Path;TargetFolder;NewTitle
```

Pour chaque ligne de l'input :
- **Path** : recopiez la valeur exacte reçue — ne pas modifier.
- **TargetFolder** : nom technique exact d'un dossier de l'arborescence du plan (ex : `1-1_Letres_de_motivation`). Choisissez le dossier dont le thème — d'après son **titre descriptif dans l'arborescence** — correspond le mieux au fichier, en vous appuyant sur ses métadonnées (chemin source, titre, date, description). N'inventez aucun dossier absent du plan. Respectez la règle de profondeur ci-dessous.
- **NewTitle** : nom normalisé selon les règles ci-dessous."""

_TACHE_REF = """\
# Tâche
À partir du plan de classement validé, produisez un CSV à 3 colonnes :

```
Ref;TargetFolder;NewTitle
```

L'input contient les colonnes `Ref;Path;CurrentTitle;Date` (et `Description` si disponible). `Path` est le **chemin source complet** du fichier : c'est un signal de classement essentiel — l'arborescence d'origine (dossiers parents) révèle souvent le thème mieux que le nom de fichier seul. Exploitez-le pleinement pour décider du `TargetFolder`.

Pour chaque ligne de l'input :
- **Ref** : recopiez **à l'identique** l'identifiant reçu (un entier). Il relie votre réponse au fichier d'origine : ne le modifiez jamais, n'en inventez aucun, produisez exactement une ligne par `Ref` reçue. **Ne recopiez pas le `Path` en sortie** — seule la `Ref` identifie le fichier.
- **TargetFolder** : nom technique exact d'un dossier de l'arborescence du plan (ex : `1-1_Letres_de_motivation`). Choisissez le dossier dont le thème — d'après son **titre descriptif dans l'arborescence** — correspond le mieux au fichier, en vous appuyant sur ses métadonnées (chemin source, titre, date, description). N'inventez aucun dossier absent du plan. Respectez la règle de profondeur ci-dessous.
- **NewTitle** : nom normalisé selon les règles ci-dessous."""


def _contexte(out_fmt: str, in_cols: str) -> str:
    return (
        "# Métadonnée de contexte\n"
        f"Si l'input contient une colonne Description en plus de {in_cols}, exploitez-la "
        "en priorité pour comprendre un fichier au nom peu parlant et produire un "
        "TargetFolder et un NewTitle pertinents. Ne la recopiez pas en sortie : la sortie "
        f"reste strictement {out_fmt}."
    )


def _build_corps(ref_mode: bool) -> str:
    """Assemble le corps du prompt selon le mode d'identifiant."""
    if ref_mode:
        tache = _TACHE_REF
        contexte = _contexte("Ref;TargetFolder;NewTitle", "Ref/Path/CurrentTitle/Date")
    else:
        tache = _TACHE_PATH
        contexte = _contexte("Path;TargetFolder;NewTitle", "Path/CurrentTitle/Date")
    return "\n\n".join([_ROLE, tache, _PROFONDEUR, contexte, _NOMMAGE])


# Bloc « Avis de classement » (la « Démarche de l'IA » côté front) — optionnel.
# Inclus ou non selon l'option : on ajoute/retire l'instruction.
_AVIS = """\
# Avis de classement
Avant le CSV, rédigez un court avis en prose (5 à 10 lignes), destiné à l'archiviste :
- pertinence générale du plan au regard des fichiers réellement présents ;
- vos choix notables et vos difficultés : tout fichier ambigu, et surtout **tout dossier du plan que vous n'avez pas rempli, avec la raison** (ex. découpage trop fin pour le volume, distinction non justifiée par les fichiers…) ;
- limites éventuelles du plan (rubrique manquante, niveau inutile, etc.).
Cet avis est informatif : il ne modifie pas le plan et n'apparaît pas dans le CSV. N'y mettez aucun bloc ```csv```."""


# Consigne d'usage des exemples de corrections — ajoutée au prompt système
# **uniquement** quand l'appelant fournit des exemples (canal optionnel, même
# modèle que la note contextuelle d'AUD-001). Le texte des exemples eux-mêmes est
# formaté côté moteur (`core.corrections.render_corrections_examples`) et placé
# dans le user message ; ce fragment se contente d'expliquer comment les honorer.
_EXEMPLES = """\
# Exemples de classements validés
Le message peut inclure des **exemples de classements déjà validés par l'archiviste** sur ce même fonds (chemin source → dossier cible, et nom normalisé). Ils font autorité : appliquez la **même logique** (choix du dossier, granularité, style de nommage) aux fichiers similaires. Ne les recopiez pas en sortie et n'inventez aucun dossier hors plan pour autant."""


# Consigne d'usage des consignes de classement de l'archiviste — ajoutée
# au prompt système **uniquement** quand l'appelant fournit des consignes (canal
# optionnel, même modèle que les exemples few-shot). Le texte des consignes lui-même est
# formaté côté moteur (`core.cla_directives.render_directives`) et placé dans le
# user message ; ce fragment explique comment les honorer, y compris la convention
# de sortie autorisant la création de sous-dossiers pour les dossiers désignés.
_DIRECTIVES = """\
# Consignes de classement de l'archiviste
Le message peut inclure des **consignes de classement** rédigées par l'archiviste, générales (au niveau du fonds) ou visant un dossier précis du plan. Elles **font autorité** : respectez-les en priorité, dans le cadre du plan validé.
- Pour une consigne visant un dossier, appliquez-la aux fichiers qui relèvent de ce dossier.
- **Création de sous-dossiers** : par défaut, n'inventez aucun dossier absent du plan. **Uniquement** lorsqu'une consigne l'**autorise explicitement** pour un dossier donné, vous pouvez créer des sous-dossiers sous ce dossier : écrivez alors `TargetFolder` sous la forme `Dossier_du_plan/Nouveau_sous_dossier` (le dossier du plan, puis « / », puis un nom court, parlant et sans extension pour le sous-dossier à créer — ex. un sous-dossier par personne, par organisme ou par affaire selon la consigne). Regroupez de façon cohérente : les fichiers d'un même ensemble (même personne, même organisme…) vont dans le **même** sous-dossier, au nom identique.
- Hors de ces autorisations, `TargetFolder` reste **un seul nom exact d'un dossier du plan**, sans « / »."""


def _livraison(avis: bool, out_fmt: str) -> str:
    """Consigne de livraison — sa numérotation dépend de la présence de l'avis,
    son format de colonnes du mode d'identifiant."""
    if avis:
        return (
            "# Livraison\n"
            "Produisez, dans cet ordre :\n"
            "1. l'avis de classement (prose, hors bloc de code) ;\n"
            "2. **puis** un seul bloc ```csv``` contenant exactement autant de lignes que "
            "de fichiers dans l'input (une ligne par fichier, dans le même ordre ; strictement "
            f"3 colonnes `{out_fmt}`, aucun commentaire à l'intérieur du CSV)."
        )
    return (
        "# Livraison\n"
        "Produisez un seul bloc ```csv``` contenant exactement autant de lignes que de "
        "fichiers dans l'input (une ligne par fichier, dans le même ordre ; strictement "
        f"3 colonnes `{out_fmt}`, aucun commentaire à l'intérieur du CSV)."
    )


def build_system_prompt(
    *,
    avis: bool = True,
    ref_mode: bool = False,
    examples: bool = False,
    directives: bool = False,
) -> str:
    """Assemble le prompt CLA-001.

    ``avis`` (défaut vrai) inclut le bloc « Avis de classement » et demande l'avis
    *puis* le CSV ; sinon seul le CSV est demandé. Mécanisme purement additif.

    ``ref_mode`` (défaut faux = méthode historique « Path ») choisit la colonne
    identifiant que le modèle recopie en sortie : ``Path`` (ancrage fort, plus
    lent) ou ``Ref`` (sortie courte, plus rapide). Cf. l'en-tête du module.

    ``examples`` (défaut faux) ajoute la consigne d'usage des **exemples de
    corrections** validés. À activer **uniquement** quand le user message porte un
    bloc d'exemples (``build_user_message(..., examples=...)``).

    ``directives`` (défaut faux) ajoute la consigne d'usage des **consignes
    de classement de l'archiviste** (et la convention de création de sous-dossiers).
    À activer **uniquement** quand le user message porte un bloc de consignes
    (``build_user_message(..., directives=...)``).

    Défauts faux ⇒ prompt système **inchangé** (byte-identique à la 1.3.0).
    """
    out_fmt = "Ref;TargetFolder;NewTitle" if ref_mode else "Path;TargetFolder;NewTitle"
    parts = [_build_corps(ref_mode)]
    if examples:
        parts.append(_EXEMPLES)
    if directives:
        parts.append(_DIRECTIVES)
    if avis:
        parts.append(_AVIS)
    parts.append(_livraison(avis, out_fmt))
    return "\n\n".join(parts) + "\n"


# Constante par défaut (avec avis, méthode historique « Path ») — conserve le
# comportement de référence.
SYSTEM_PROMPT = build_system_prompt()


# Frontière de cache de prompt : dans le user message, tout ce qui précède
# ce marqueur (le **plan de classement validé**) est identique d'un lot à
# l'autre — seule la liste des fichiers change. Le provider Anthropic place un
# `cache_control` sur ce préfixe stable (cf. `LiteLLMProvider._build_messages`).
# Le texte du prompt est inchangé : ce n'est qu'un point de découpe, pas une
# modification de contenu (aucun bump de PROMPT_VERSION).
CACHE_BOUNDARY = "**Fichiers à classer :**"


def build_user_message(
    csv_content: str,
    plan_valide: str,
    *,
    ref_mode: bool = False,
    examples: str | None = None,
    directives: str | None = None,
) -> str:
    """Assemble le user message CLA-001.

    ``examples`` : bloc Markdown d'**exemples de corrections** validés (rendu
    par ``core.corrections.render_corrections_examples``). Inséré entre le plan et
    la liste des fichiers — donc dans le **préfixe stable** mis en cache (
    avant ``CACHE_BOUNDARY``), les exemples étant constants d'un lot à l'autre.

    ``directives`` : bloc Markdown de **consignes de classement** de
    l'archiviste (rendu par ``core.cla_directives.render_directives``). Inséré au
    même endroit — dans le préfixe stable mis en cache (constant d'un lot à l'autre).

    ``examples``/``directives`` ``None`` ou vides ⇒ user message **inchangé**
    (byte-identique à la 1.3.0).
    """
    if ref_mode:
        id_instr = "Ref (recopiée à l'identique)"
    else:
        id_instr = "Path (inchangé)"
    examples_block = f"{examples.strip()}\n\n" if examples and examples.strip() else ""
    directives_block = f"{directives.strip()}\n\n" if directives and directives.strip() else ""
    return (
        "**Plan de classement validé :**\n"
        f"{plan_valide}\n\n"
        f"{examples_block}"
        f"{directives_block}"
        f"{CACHE_BOUNDARY}\n"
        "```csv\n"
        f"{csv_content}\n"
        "```\n\n"
        "Produisez le CSV dans un bloc ```csv``` avec les 3 colonnes : "
        f"{id_instr} ; TargetFolder (nom exact du plan) ; NewTitle (nom normalisé)."
    )
