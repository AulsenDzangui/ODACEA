"""Limiteur d'usage pour le mode démonstration (`DEMO_MODE`).

Conçu pour une démo publique adossée à une clé OpenAI partagée. Deux protections
complémentaires :

  * **N essais par IP, par étape et par jour** : une IP peut lancer l'audit et le
    classement jusqu'à ``MAX_TRIES_PER_STAGE`` fois par journée (UTC). Au-delà → refus.
  * **Plafond global de tokens par jour** : somme des tokens facturés sur
    l'ensemble des appels. Au-delà → refus, jusqu'au lendemain.

Modèle **transactionnel** pour fermer la fenêtre TOCTOU : :func:`begin` réserve
*atomiquement* un essai **et** provisionne des tokens **avant** l'appel LLM ; on
solde ensuite avec :func:`commit` (succès, réconcilie l'usage réel) ou
:func:`rollback` (échec / abandon, rend l'essai et les tokens). Sans cela, des
requêtes concurrentes verraient toutes le compteur encore à zéro et passeraient.

Tout est **en mémoire et éphémère** : rien n'est écrit sur disque ni journalisé,
conformément à la minimisation des données (RGPD). L'adresse IP n'est **jamais**
conservée en clair — seul un condensé SHA-256 salé est gardé en mémoire pour la
journée courante, puis purgé au changement de jour ou au redémarrage du service.

Garde-fou budgétaire : comme les compteurs se réinitialisent au redémarrage
(Render peut mettre le service en veille), ce plafond reste **souple**. La seule
garantie dure contre la facture est un plafond de dépense fixé dans le tableau de
bord OpenAI — à conserver impérativement.
"""
from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

# Sel de hachage de l'IP. Aléatoire au démarrage si non fourni : comme rien n'est
# persisté, un sel volatil suffit et renforce l'anonymisation (le condensé n'a
# aucune valeur hors du processus courant).
_SALT = os.getenv("DEMO_IP_SALT") or os.urandom(16).hex()

# Plafond quotidien de tokens (entrée + sortie cumulés), partagé par tous.
DAILY_TOKEN_CAP = int(os.getenv("DEMO_DAILY_TOKEN_CAP", "200000"))
# Essais autorisés par IP, par étape (audit / classement) et par jour.
MAX_TRIES_PER_STAGE = int(os.getenv("DEMO_MAX_TRIES_PER_STAGE", "2"))
# Tokens provisionnés à l'ouverture d'un appel, avant de connaître l'usage réel
# (réconcilié à la valeur exacte au commit). Borne le dépassement possible du
# plafond par les appels concurrents en vol à ~une réservation par appel.
RESERVE_TOKENS = int(os.getenv("DEMO_RESERVE_TOKENS", "15000"))

_lock = threading.Lock()
_day: str = ""
# hash_ip -> {"audit": essais_consommés, "classement": essais_consommés}
_ip_usage: dict[str, dict[str, int]] = {}
_tokens_today: int = 0


class DemoLimitError(Exception):
    """Quota dépassé. ``message`` est rédigé pour l'utilisateur final."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class Reservation:
    """Jeton rendu par :func:`begin`, à solder par :func:`commit` (succès) ou
    :func:`rollback` (échec / abandon). Identifie l'essai provisionné et le
    montant de tokens à réconcilier."""

    ip_hash: str
    stage: str
    reserved_tokens: int


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _roll_day_locked() -> None:
    """Réinitialise les compteurs au changement de jour. À appeler sous ``_lock``."""
    global _day, _ip_usage, _tokens_today
    d = _today()
    if d != _day:
        _day = d
        _ip_usage = {}
        _tokens_today = 0


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(f"{_SALT}:{ip}".encode()).hexdigest()


def begin(ip: str, stage: str) -> Reservation:
    """Réserve *atomiquement* un essai pour cette IP/étape et provisionne des
    tokens, **avant** tout appel LLM.

    ``stage`` ∈ {"audit", "classement"}. Lève :class:`DemoLimitError` si l'IP a
    épuisé ses essais du jour pour l'étape, ou si le plafond global est atteint.
    Réserver à l'entrée (plutôt que comptabiliser à la fin) ferme la fenêtre
    TOCTOU : deux requêtes concurrentes de la même IP ne peuvent pas passer
    toutes les deux. Solder ensuite via :func:`commit` ou :func:`rollback`.
    """
    global _tokens_today
    h = _hash_ip(ip)
    with _lock:
        _roll_day_locked()
        if _tokens_today >= DAILY_TOKEN_CAP:
            raise DemoLimitError(
                "Le quota quotidien partagé de la démonstration est atteint. "
                "Merci de réessayer demain."
            )
        if _ip_usage.get(h, {}).get(stage, 0) >= MAX_TRIES_PER_STAGE:
            raise DemoLimitError(
                f"Vous avez atteint la limite de {MAX_TRIES_PER_STAGE} essais du "
                "jour pour cette étape. La démonstration est limitée par jour et "
                "par visiteur."
            )
        _ip_usage.setdefault(h, {})[stage] = _ip_usage.get(h, {}).get(stage, 0) + 1
        _tokens_today += RESERVE_TOKENS
        return Reservation(ip_hash=h, stage=stage, reserved_tokens=RESERVE_TOKENS)


def commit(res: Reservation, actual_tokens: int | None) -> None:
    """Solde une réservation après un appel réussi : remplace les tokens
    provisionnés par l'usage réel. L'essai reste consommé."""
    global _tokens_today
    with _lock:
        _roll_day_locked()
        delta = (int(actual_tokens) if actual_tokens else 0) - res.reserved_tokens
        _tokens_today = max(0, _tokens_today + delta)


def rollback(res: Reservation) -> None:
    """Annule une réservation (échec LLM, abandon) : rend l'essai et les tokens
    provisionnés, pour qu'un échec ne pénalise pas le visiteur."""
    global _tokens_today
    with _lock:
        _roll_day_locked()
        _tokens_today = max(0, _tokens_today - res.reserved_tokens)
        u = _ip_usage.get(res.ip_hash)
        if u and u.get(res.stage, 0) > 0:
            u[res.stage] -= 1


def snapshot() -> dict:
    """État courant (pour affichage). N'expose aucune donnée personnelle."""
    with _lock:
        _roll_day_locked()
        return {
            "day": _day,
            "tokensToday": _tokens_today,
            "tokenCap": DAILY_TOKEN_CAP,
            "tokensRemaining": max(0, DAILY_TOKEN_CAP - _tokens_today),
            "maxTriesPerStage": MAX_TRIES_PER_STAGE,
        }
