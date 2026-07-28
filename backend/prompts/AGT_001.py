# -----------------------------------------------------------------------------
# Prompt AGT-001 (texte) — © 2026 Aulsen Dzangui — Licence CC BY-SA 4.0
# Le texte des chaînes SYSTEM_PROMPT* ci-dessous est sous CC BY-SA 4.0 (voir
# LICENSE-PROMPTS à la racine du dépôt). Le code Python l'entourant reste sous
# AGPL-3.0 (voir LICENSE).
# -----------------------------------------------------------------------------
#
# Agent conversationnel d'exploration de vrac — lecture seule : il aide
# à rechercher et naviguer dans le fonds, jamais à le modifier. Deux modes
# d'appel des outils, même prompt métier :
#   - mode natif : le fournisseur supporte le function calling → les outils sont
#     déclarés via TOOLS (schémas OpenAI), le prompt n'explique pas la syntaxe ;
#   - repli JSON (petits modèles locaux au tool-calling faible — risque n°1 du
#     lot) : _JSON_PROTOCOL contraint la sortie à UN objet JSON par tour, choisi
#     parmi les opérations typées.
#
# Le modèle ne voit JAMAIS le CSV : uniquement le résumé compact du vrac
# (digest audit_scan, injecté par build_system_prompt) et les résultats
# d'outils, paginés et totalisés côté Python (core/agt_tools.py).

# Version du prompt : à incrémenter à CHAQUE
# modification du texte. Renvoyée dans les `done{promptVersion}` de l'API ;
# l'éval dédiée (golden files des requêtes attendues) vit dans evals/cases/.
# 0.2.0 : outil `classer` — l'agent prépare des opérations de classement
# (mouvements en attente, validés par l'archiviste), fin du « lecture seule ».
# 0.3.0 : outil `noter` — les faits validés au fil du dialogue deviennent
# des notes de connaissance (éditables par l'archiviste, réinjectables dans
# CLA-001 pour le reliquat) ; les notes existantes sont rappelées dans le
# system prompt (préfixe stable).
# 0.4.0 : outil `mots_frequents` — top-N exact des termes chemins+titres ;
# les questions de thématiques/mots-clés reçoivent un comptage déterministe au
# lieu d'une déduction depuis un échantillon (+ règle d'usage dédiée).
# 0.5.0 : retrait des outils `classer` et `noter` (et des notes de connaissance
# qui en dépendaient) — décision utilisateur de recentrer l'agent sur la seule
# **exploration/recherche** du fonds, plus aucune capacité de classement, de
# renommage ni de mémorisation de faits. Redevenu strictement lecture seule.
# 0.6.0 : canal **optionnel** `audit_report` — le rapport d'audit du projet
# (AUD-001) peut être injecté comme contexte de la session (bloc stable, après
# le digest). Opt-in, comme la note contextuelle d'AUD-001 : quand aucun rapport
# n'est fourni, le system prompt est **byte-identique** à la 0.5.0 (aucune
# régression pour l'exploration « à froid »). Ses constats mécaniques reprennent
# le même digest déterministe ; son plan reste une proposition, et la règle
# « jamais de chiffre de tête » prime toujours (tout chiffre cité vient d'un outil).
PROMPT_VERSION = "0.6.0"

_ROLE = """\
## Rôle

Vous êtes un assistant archiviste : vous aidez à **explorer** et **rechercher** dans un \
vrac bureautique (volumes, types de fichiers, périodes, doublons, organisation) à partir \
de ses seules métadonnées (chemins, noms, dates — jamais le contenu des documents).

## Règles impératives

* **Jamais de chiffre « de tête »** : tout comptage, toute liste, toute répartition \
provient d'un appel d'outil. Si vous n'avez pas encore le chiffre, appelez l'outil.
* Les résultats d'outils sont **paginés** : `total` est toujours exact ; ne dites \
jamais qu'il n'y a que N éléments parce que la page en montre N.
* Pour les **principaux mots-clés ou thématiques** du vrac (ou d'un sous-ensemble), \
appelez `mots_frequents` : il compte les termes sur **tout** le périmètre. Ne déduisez \
jamais les thématiques d'un échantillon.
* Répondez en **français**, de façon concise et factuelle ; citez les chemins tels quels.
* Vous ne pouvez **rien modifier ni supprimer** : vous n'êtes ici que pour aider à \
chercher et naviguer dans le fonds. Si l'archiviste demande un classement, un \
renommage ou toute autre action sur les fichiers, indiquez que cela ne fait pas partie \
de vos capacités.

## Résumé du vrac (constats mécaniques exacts, calculés sur tout le fonds)
"""

# Bloc contextuel optionnel (0.6.0) : le rapport d'audit du projet, injecté
# APRÈS le digest. Encadré comme « analyse retenue » (contexte), pas comme
# suspect : ses constats mécaniques reprennent le même digest déterministe déjà
# présent ci-dessus, seul le plan/les recommandations relèvent de l'interprétation.
# La règle « jamais de chiffre de tête » (déjà dans _ROLE) prime quelle que soit
# l'origine du chiffre — inutile de jeter le doute sur des mesures solides.
_AUDIT_REPORT_HEADER = """\

## Rapport d'audit du projet (analyse retenue pour ce fonds)

Ce rapport a été produit lors de l'audit de ce même vrac. Ses constats mécaniques \
(volumétrie, formats, doublons) reprennent les mêmes mesures déterministes que le \
résumé ci-dessus ; son **plan de classement** et ses recommandations sont des \
**propositions** que l'archiviste peut vouloir creuser ou vérifier avec vous. \
Appuyez-vous dessus pour orienter vos recherches — mais tout comptage que vous \
citez provient d'un appel d'outil, quelle que soit son origine.
"""

# Protocole du repli JSON : UN objet JSON par réponse, rien d'autre.
_JSON_PROTOCOL = """\

## Format de réponse (obligatoire)

Répondez toujours par **un seul objet JSON**, sans texte autour, choisi parmi :

1. Appeler un outil :
   {"outil": "<nom>", "arguments": {…}}
2. Donner la réponse finale à l'archiviste :
   {"reponse": "texte de la réponse"}

Outils disponibles (arguments entre parenthèses) :
* chercher(mots_cles: [chaînes], page: entier = 0) — recherche mots-clés (ET, \
insensible casse/accents) sur chemins et titres, fichiers et dossiers.
* lister_dossier(chemin: chaîne = ".", page: entier = 0) — contenu direct d'un \
dossier ("." = racine) : sous-dossiers puis fichiers.
* compter(filtre: objet = {}) — nombre exact de fichiers satisfaisant le filtre.
* echantillonner(filtre: objet = {}, n: entier = 5) — échantillon représentatif.
* stats(par: "extension" | "periode" | "dossier") — répartition exacte des fichiers.
* mots_frequents(filtre: objet = {}, n: entier = 20) — termes les plus fréquents \
des chemins et titres (comptage exact sur tout le périmètre, mots vides écartés) ; \
à utiliser pour les questions de thématiques/mots-clés.

Le filtre est un objet aux clés optionnelles : mots_cles ([chaînes], ET), \
extension (chaîne, ex. "pdf"), dossier (chaîne, chemin d'un sous-dossier), \
annee_min (entier), annee_max (entier).
"""


def build_system_prompt(
    digest: str, json_mode: bool = False, audit_report: str | None = None
) -> str:
    """Assemble le system prompt : rôle + résumé compact du vrac, éventuellement
    suivi du rapport d'audit du projet (canal **optionnel** `audit_report`), puis
    le protocole JSON en mode repli. Stable sur toute la session — préfixe
    cacheable.

    **Byte-identique à la 0.5.0 quand `audit_report` est vide/None** : le canal
    est opt-in (comme la note contextuelle d'AUD-001) — l'exploration « à froid »
    (agent ouvert avant l'audit, ou toggle désactivé) n'en paie pas les tokens."""
    parts = [_ROLE, digest.strip() or "(résumé indisponible)"]
    if audit_report and audit_report.strip():
        parts.append(_AUDIT_REPORT_HEADER + "\n" + audit_report.strip())
    if json_mode:
        parts.append(_JSON_PROTOCOL)
    return "\n".join(parts)


# ── Schémas d'outils (function calling natif, format OpenAI) ──────────────────

_FILTRE_SCHEMA = {
    "type": "object",
    "description": (
        "Filtre structuré sur les fichiers. Toutes les clés sont optionnelles ; "
        "elles se combinent en ET."
    ),
    "properties": {
        "mots_cles": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Mots-clés (ET, insensible casse/accents) sur chemin + titre.",
        },
        "extension": {"type": "string", "description": "Extension de fichier, ex. \"pdf\"."},
        "dossier": {
            "type": "string",
            "description": "Chemin d'un sous-dossier : ne garder que sa sous-arborescence.",
        },
        "annee_min": {"type": "integer", "description": "Année minimale (Content.StartDate)."},
        "annee_max": {"type": "integer", "description": "Année maximale (Content.StartDate)."},
    },
    "additionalProperties": False,
}

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "chercher",
            "description": (
                "Recherche par mots-clés (ET, insensible à la casse et aux accents) "
                "sur les chemins et titres — fichiers et dossiers. Résultats paginés, "
                "total exact."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mots_cles": {"type": "array", "items": {"type": "string"}},
                    "page": {"type": "integer", "description": "Page de résultats (0 = première)."},
                },
                "required": ["mots_cles"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lister_dossier",
            "description": (
                "Contenu direct d'un dossier (\".\" = racine du fonds) : sous-dossiers "
                "avec leur nombre de fichiers, puis fichiers (paginés)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chemin": {"type": "string", "description": "Chemin du dossier (\".\" = racine)."},
                    "page": {"type": "integer"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compter",
            "description": "Nombre exact de fichiers satisfaisant le filtre (+ répartition par extension).",
            "parameters": {
                "type": "object",
                "properties": {"filtre": _FILTRE_SCHEMA},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "echantillonner",
            "description": "Échantillon déterministe de fichiers satisfaisant le filtre.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filtre": _FILTRE_SCHEMA,
                    "n": {"type": "integer", "description": "Taille d'échantillon (défaut 5)."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stats",
            "description": "Répartition exacte des fichiers par extension, periode (année) ou dossier.",
            "parameters": {
                "type": "object",
                "properties": {
                    "par": {"type": "string", "enum": ["extension", "periode", "dossier"]},
                },
                "required": ["par"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mots_frequents",
            "description": (
                "Termes les plus fréquents des chemins et titres — comptage exact "
                "sur tout le vrac ou le sous-ensemble filtré (mots vides français "
                "écartés) ; l'occurrence est le nombre de fichiers portant le terme. "
                "À utiliser pour « principaux mots-clés / thématiques », jamais un "
                "échantillon."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filtre": _FILTRE_SCHEMA,
                    "n": {"type": "integer", "description": "Nombre de termes (défaut 20)."},
                },
                "additionalProperties": False,
            },
        },
    },
]
