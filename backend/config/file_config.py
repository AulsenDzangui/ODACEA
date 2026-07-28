"""Fichier de configuration `odacea.toml`.

Permet de fixer le modèle, la `base_url` et les options de préparation par
défaut, pour éviter de répéter les flags à chaque invocation de la CLI.

**Précédence : CLI > config > `.env`/défauts intégrés.** Une option non passée
en ligne de commande prend la valeur du fichier de configuration si elle y est
définie, sinon la valeur par défaut intégrée (ou `DEFAULT_MODEL` du `.env` pour
le modèle).

Le fichier est cherché via `--config`, sinon `odacea.toml` est remonté depuis le
répertoire courant (comme `.git`). Format (toutes les clés sont facultatives) :

    [llm]
    model = "gpt-5.1"
    base_url = "http://localhost:1234/v1"

    [prep]
    filter_columns = true
    clean_dates = true
    sample_items = true
    sample_n = 5
    include_items = true
    auto_measures = true
    description = false

    [classement]
    batch_size = 50
    avis = true
    ref = false
    concurrency = 1
"""
from __future__ import annotations

from pathlib import Path

import tomllib

CONFIG_FILENAME = "odacea.toml"

# Sections et clés reconnues — toute autre est signalée (coquille probable).
# Le type attendu sert à valider le fichier (bool / int / str).
_SCHEMA: dict[str, dict[str, type]] = {
    "llm": {"model": str, "base_url": str},
    "prep": {
        "filter_columns": bool,
        "clean_dates": bool,
        "sample_items": bool,
        "sample_n": int,
        "include_items": bool,
        "auto_measures": bool,
        "description": bool,
    },
    "classement": {"batch_size": int, "avis": bool, "ref": bool, "concurrency": int},
}


class ConfigError(ValueError):
    """Fichier `odacea.toml` introuvable, illisible ou invalide."""


def discover_config(explicit: str | None, start: Path | None = None) -> Path | None:
    """Localise le fichier de configuration.

    `--config` explicite (erreur s'il est introuvable), sinon `odacea.toml`
    remonté depuis `start` (par défaut le répertoire courant) jusqu'à la racine.
    Retourne `None` si aucun fichier n'est trouvé en l'absence de `--config`.
    """
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise ConfigError(f"Fichier de configuration introuvable : {p}")
        return p
    base = (start or Path.cwd()).resolve()
    for d in (base, *base.parents):
        candidate = d / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path) -> tuple[dict, list[str]]:
    """Lit et valide `odacea.toml`.

    Retourne `(config, warnings)` où `config` ne contient que les sections/clés
    reconnues et `warnings` liste les sections/clés inconnues (non bloquant —
    une coquille ne doit pas faire échouer le run, mais doit être visible).
    Lève `ConfigError` si le fichier est illisible, malformé, ou si une valeur
    reconnue est du mauvais type.
    """
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except OSError as e:
        raise ConfigError(f"{path} illisible : {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} : TOML invalide — {e}") from e

    config: dict = {}
    warnings: list[str] = []
    for section, values in raw.items():
        if section not in _SCHEMA:
            warnings.append(f"section inconnue ignorée : [{section}]")
            continue
        if not isinstance(values, dict):
            raise ConfigError(f"{path} : [{section}] doit être une table TOML.")
        known = _SCHEMA[section]
        kept: dict = {}
        for key, value in values.items():
            expected = known.get(key)
            if expected is None:
                warnings.append(f"clé inconnue ignorée : [{section}].{key}")
                continue
            # bool est une sous-classe d'int : on refuse un bool là où un int est
            # attendu (et inversement) pour ne pas masquer une erreur de frappe.
            if expected is int:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ConfigError(
                        f"{path} : [{section}].{key} doit être un entier (reçu : {value!r})."
                    )
            elif not isinstance(value, expected):
                raise ConfigError(
                    f"{path} : [{section}].{key} doit être de type "
                    f"{expected.__name__} (reçu : {value!r})."
                )
            kept[key] = value
        if kept:
            config[section] = kept
    return config, warnings


def section_get(config: dict, section: str, key: str):
    """Valeur d'une clé de config, ou `None` si absente."""
    return config.get(section, {}).get(key)
