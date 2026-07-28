"""Estimation et comptabilité des tokens.

Porté de `web/lib/tokens/estimate.ts` et `web/components/token-usage-bar.tsx`
pour aligner la version Streamlit sur la version web :

- `estimate_tokens` : estimation a priori (avant lancement) du coût AUD-001 +
  CLA-001, en tenant compte du découpage en lots.
- `format_tokens` : formatage lisible (k).
- `sum_usage` / `format_usage_line` : agrégation et affichage de l'usage réel
  renvoyé par le serveur (cf. LiteLLMProvider.last_usage).
"""

import math

import pandas as pd

from core.csv_handler import (
    classement_llm_csv,
    csv_to_string,
    prepare_for_classement,
    prepare_for_llm,
)
from prompts.AUD_001 import SYSTEM_PROMPT as AUD_SYSTEM
from prompts.AUD_001 import build_user_message as build_aud_msg
from prompts.CLA_001 import SYSTEM_PROMPT as CLA_SYSTEM
from prompts.CLA_001 import build_user_message as build_cla_msg

# Approximation conservatrice : les métadonnées archivistiques (chemins + dates +
# titres français) sont plus denses que l'anglais pur mais moins que du code →
# 3,5 caractères/token est raisonnable. Identique à la version web.
CHARS_PER_TOKEN = 3.5


def _chars_to_tokens(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


def estimate_text_tokens(text: str) -> int:
    """Estimation a priori du nombre de tokens d'un texte (~3,5 car./token).

    Variante publique de `_chars_to_tokens` pour estimer le coût d'un prompt
    déjà assemblé (cf. le mode `--dry-run` de la CLI)."""
    return _chars_to_tokens(len(text))


def estimate_tokens(
    df: pd.DataFrame,
    *,
    filter_columns: bool = True,
    clean_dates: bool = True,
    sample_items_n: int = 0,
    include_description: bool = False,
    include_items: bool = True,
    batch_size: int = 0,
) -> dict:
    """Estime le coût en tokens d'entrée pour AUD-001 et CLA-001.

    Retourne un dict : audit_tokens, classement_tokens_per_batch,
    classement_batches, classement_total_tokens, total_tokens.
    Le plan d'audit (non connu à ce stade) est exclu de l'estimation CLA-001.
    `include_items=False` (arborescence seule) ne concerne que l'audit — le
    classement traite toujours tous les Item.
    """
    # ── AUD-001 ──────────────────────────────────────────────────────────────
    prepared = prepare_for_llm(
        df,
        filter_columns=filter_columns,
        clean_dates=clean_dates,
        sample_items_n=sample_items_n,
        include_description=include_description,
        include_items=include_items,
    )
    audit_csv = csv_to_string(prepared)
    audit_user_msg = build_aud_msg(audit_csv, observation="")
    audit_tokens = _chars_to_tokens(len(AUD_SYSTEM) + len(audit_user_msg))

    # ── CLA-001 ──────────────────────────────────────────────────────────────
    items = prepare_for_classement(df, include_description=include_description)
    n = len(items)
    size = batch_size if batch_size > 0 else (n or 1)
    if n == 0:
        batches = []
    else:
        batches = [items.iloc[i:i + size] for i in range(0, n, size)]
    classement_batches = len(batches) or 1

    # Boilerplate fixe du message CLA-001 (hors plan et CSV), calculé depuis le
    # builder réel pour rester synchronisé avec le prompt.
    cla_base_chars = len(CLA_SYSTEM) + len(build_cla_msg(csv_content="", plan_valide=""))
    per_batch = [
        _chars_to_tokens(cla_base_chars + len(classement_llm_csv(batch)))
        for batch in batches
    ]

    classement_tokens_per_batch = per_batch[0] if per_batch else _chars_to_tokens(cla_base_chars)
    classement_total_tokens = sum(per_batch) if per_batch else classement_tokens_per_batch

    return {
        "audit_tokens": audit_tokens,
        "classement_tokens_per_batch": classement_tokens_per_batch,
        "classement_batches": classement_batches,
        "classement_total_tokens": classement_total_tokens,
        "total_tokens": audit_tokens + classement_total_tokens,
    }


def format_tokens(n: int) -> str:
    """Formate un nombre de tokens : '850', '1,5 k', '12,3 k'."""
    if n < 1000:
        return str(n)
    return f"{n / 1000:.1f}".replace(".", ",") + " k"


def format_duration(seconds: float) -> str:
    """Formate une durée (en secondes) en texte lisible français.

    Pendant déterministe de `format_usage_line` côté temps de traitement, pour
    la mesure de performance demandée (durée par agent + total session) :

    - < 60 s  → '0,3 s', '12,4 s' (une décimale)
    - < 1 h   → '3 min 05 s'
    - ≥ 1 h   → '1 h 02 min'

    Négatif ou non fini (NaN/inf) est ramené à 0.
    """
    if not math.isfinite(seconds) or seconds < 0:
        seconds = 0.0
    if seconds < 60:
        return f"{seconds:.1f}".replace(".", ",") + " s"
    if seconds < 3600:
        minutes, secs = divmod(int(round(seconds)), 60)
        return f"{minutes} min {secs:02d} s"
    hours, rem = divmod(int(round(seconds)), 3600)
    minutes = rem // 60
    return f"{hours} h {minutes:02d} min"


# ── Usage réel (post-appel) ──────────────────────────────────────────────────

_USAGE_KEYS = ("input_tokens", "output_tokens", "total_tokens",
               "cache_read_tokens", "reasoning_tokens")


def sum_usage(usages: list[dict | None]) -> dict | None:
    """Agrège une liste d'usages (cf. LiteLLMProvider.last_usage).

    Ignore les None et ceux sans total_tokens. Retourne None si rien d'exploitable.
    """
    valid = [u for u in usages if u and u.get("total_tokens")]
    if not valid:
        return None
    out = {k: 0 for k in _USAGE_KEYS}
    for u in valid:
        for k in _USAGE_KEYS:
            out[k] += u.get(k) or 0
    return out


def format_usage_line(usage: dict | None, label: str = "") -> str:
    """Construit la ligne d'affichage de l'usage réel. '' si rien à montrer."""
    if not usage or not usage.get("total_tokens"):
        return ""
    parts = []
    if usage.get("input_tokens") is not None:
        parts.append(f"entrée : {format_tokens(usage['input_tokens'])}")
    if usage.get("output_tokens") is not None:
        parts.append(f"sortie : {format_tokens(usage['output_tokens'])}")
    if usage.get("cache_read_tokens"):
        parts.append(f"cache : {format_tokens(usage['cache_read_tokens'])}")
    if usage.get("reasoning_tokens"):
        parts.append(f"thinking : {format_tokens(usage['reasoning_tokens'])}")

    prefix = f"**{label}** — " if label else ""
    detail = f" ({' · '.join(parts)})" if parts else ""
    return f"{prefix}{format_tokens(usage['total_tokens'])} tokens réels{detail}"
