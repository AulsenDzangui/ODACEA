"""Estimation de coût € pour les modèles cloud connus.

À côté de l'estimation de tokens (`core.tokens`), cette table **locale et datée**
convertit un volume de tokens en un **coût indicatif en euros** pour les modèles
cloud reconnus. Objectifs et limites assumés :

- **Indicatif, pas contractuel** : les tarifs des fournisseurs évoluent et sont
  publiés en USD ; les valeurs ci-dessous sont des ordres de grandeur convertis
  en € à une date donnée (`PRICE_TABLE_DATE`). L'archiviste doit pouvoir les
  réviser sans toucher au reste du moteur — d'où une simple table éditable.
- **Rien pour les locaux** : un modèle servi en local (Ollama, LM Studio, JAN —
  tout modèle avec `base_url`, ou préfixe local) ne coûte rien au token ;
  `model_pricing` renvoie alors `None` et aucun coût n'est affiché.
- **Rien pour un cloud inconnu** : pas d'extrapolation — un modèle absent de la
  table renvoie `None` (mieux vaut ne rien afficher qu'un chiffre faux).

Source unique : CLI (`--dry-run`) et API (`/parse`) consomment ces fonctions ;
le front ne fait que présenter le montant.
"""
from __future__ import annotations

from config.settings import LOCAL_MODEL_PREFIXES

# Date de la grille tarifaire (à mettre à jour avec les valeurs). Affichée à côté
# du montant pour que l'archiviste sache de quand datent les prix.
PRICE_TABLE_DATE = "2026-06-14"

# Prix indicatifs en **euros par million de tokens** (entrée, sortie). Convertis
# approximativement depuis les tarifs publics USD au taux ~0,92 €/$ — valeurs
# arrondies, à réviser. La table est ordonnée du plus **spécifique** au plus
# général : le premier motif (`match`, sous-chaîne insensible à la casse) trouvé
# dans l'identifiant du modèle l'emporte (p. ex. « mini »/« nano »/« haiku »
# avant la famille large). `label` sert à l'affichage.
#
# ── Pour mettre à jour : éditer les valeurs ci-dessous et `PRICE_TABLE_DATE`. ──
#
# Attention à l'ordre : un motif court contenu dans un autre nom doit venir
# **après** (p. ex. « gemini » contient « mini » → tout le bloc Gemini précède le
# motif générique « mini » pour ne pas le capter à tort).
PRICE_TABLE: list[dict] = [
    # Anthropic Claude
    {"match": "claude-haiku", "label": "Claude Haiku", "inputEurPerM": 0.7, "outputEurPerM": 3.7},
    {"match": "claude-opus", "label": "Claude Opus", "inputEurPerM": 13.8, "outputEurPerM": 69.0},
    {"match": "claude-sonnet", "label": "Claude Sonnet", "inputEurPerM": 2.8, "outputEurPerM": 13.8},
    {"match": "claude-fable", "label": "Claude Fable", "inputEurPerM": 2.8, "outputEurPerM": 13.8},
    # Google Gemini (avant les motifs génériques « mini »/« flash »)
    {"match": "gemini-2.5-flash", "label": "Gemini Flash", "inputEurPerM": 0.28, "outputEurPerM": 2.3},
    {"match": "gemini-1.5-flash", "label": "Gemini Flash", "inputEurPerM": 0.07, "outputEurPerM": 0.28},
    {"match": "gemini", "label": "Gemini Pro", "inputEurPerM": 1.15, "outputEurPerM": 9.2},
    {"match": "flash", "label": "Gemini Flash", "inputEurPerM": 0.28, "outputEurPerM": 2.3},
    # OpenAI GPT / o-series (les variantes courtes d'abord)
    {"match": "gpt-5-nano", "label": "GPT-5 nano", "inputEurPerM": 0.05, "outputEurPerM": 0.37},
    {"match": "gpt-5-mini", "label": "GPT-5 mini", "inputEurPerM": 0.23, "outputEurPerM": 1.84},
    {"match": "mini", "label": "GPT mini", "inputEurPerM": 0.23, "outputEurPerM": 1.84},
    {"match": "o3", "label": "OpenAI o3", "inputEurPerM": 1.84, "outputEurPerM": 7.36},
    {"match": "o1", "label": "OpenAI o1", "inputEurPerM": 13.8, "outputEurPerM": 55.2},
    {"match": "gpt-5", "label": "GPT-5", "inputEurPerM": 1.15, "outputEurPerM": 9.2},
    {"match": "gpt-4o", "label": "GPT-4o", "inputEurPerM": 2.3, "outputEurPerM": 9.2},
    {"match": "gpt-4", "label": "GPT-4", "inputEurPerM": 2.3, "outputEurPerM": 9.2},
]


def is_local(model: str, base_url: str | None = None) -> bool:
    """Vrai pour un modèle servi en local (aucun coût au token).

    Tout `base_url` renseigné = serveur local (LM Studio/JAN/Ollama/proxy), ou un
    préfixe de modèle local (cf. `config.settings.LOCAL_MODEL_PREFIXES`)."""
    if base_url:
        return True
    m = (model or "").strip().lower()
    return any(m.startswith(p) for p in LOCAL_MODEL_PREFIXES)


def model_pricing(model: str, base_url: str | None = None) -> dict | None:
    """Tarif (€/M tokens) du modèle, ou `None` si local ou cloud inconnu.

    Retourne `{label, inputEurPerM, outputEurPerM, priceDate, model}`.
    """
    if not model or is_local(model, base_url):
        return None
    m = model.strip().lower()
    for entry in PRICE_TABLE:
        if entry["match"] in m:
            return {
                "label": entry["label"],
                "inputEurPerM": entry["inputEurPerM"],
                "outputEurPerM": entry["outputEurPerM"],
                "priceDate": PRICE_TABLE_DATE,
                "model": model,
            }
    return None


def estimate_cost_eur(
    *,
    model: str,
    base_url: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> dict | None:
    """Coût indicatif € pour un volume de tokens, ou `None` (local/inconnu).

    Retourne `{inputEur, outputEur, totalEur, label, priceDate, model,
    inputEurPerM, outputEurPerM}`. L'estimation a priori (avant run) ne connaît
    que les tokens d'**entrée** ; passer `output_tokens=0` donne alors le coût
    d'entrée seul (`outputEur=0`) — c'est le cas du `--dry-run` / `/parse`.
    """
    pricing = model_pricing(model, base_url)
    if pricing is None:
        return None
    input_eur = max(input_tokens, 0) / 1_000_000 * pricing["inputEurPerM"]
    output_eur = max(output_tokens, 0) / 1_000_000 * pricing["outputEurPerM"]
    return {
        "label": pricing["label"],
        "model": model,
        "priceDate": pricing["priceDate"],
        "inputEurPerM": pricing["inputEurPerM"],
        "outputEurPerM": pricing["outputEurPerM"],
        "inputEur": round(input_eur, 6),
        "outputEur": round(output_eur, 6),
        "totalEur": round(input_eur + output_eur, 6),
    }


def format_cost_eur(amount: float | None) -> str:
    """Formate un montant € lisible : '0,12 €', '1,30 €', '< 0,01 €', '12,40 €'.

    `None` (modèle local/inconnu) → '' (rien à afficher)."""
    if amount is None:
        return ""
    if amount <= 0:
        return "0,00 €"
    if amount < 0.01:
        return "< 0,01 €"
    return f"{amount:.2f}".replace(".", ",") + " €"
