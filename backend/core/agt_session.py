"""Sessions de travail de l'agent.

**Dérogation documentée au non-objectif « backend sans état »** (CDC §14,
2026-07-02) : l'agent conversationnel a besoin d'un DataFrame vivant entre deux
tours de dialogue. Les sessions vivent **en mémoire process** avec TTL et
éviction — pas de base de données, pas de persistance durable côté serveur,
pas de multi-utilisateur. L'état serveur est un **cache de travail** : une
session expirée est recréable à l'identique depuis le projet client (le front
renvoie le CSV, comme pour tout autre endpoint) — jamais la seule copie.

Réglages par variables d'environnement : `ODACEA_AGT_TTL_S` (défaut 1800 s),
`ODACEA_AGT_MAX_SESSIONS` (défaut 4 — outil mono-poste).
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

DEFAULT_TTL_S = int(os.getenv("ODACEA_AGT_TTL_S", "1800"))
DEFAULT_MAX_SESSIONS = int(os.getenv("ODACEA_AGT_MAX_SESSIONS", "4"))


class SessionNotFound(KeyError):
    """Session inconnue ou expirée : le client la recrée depuis son projet."""


@dataclass
class AgentSession:
    session_id: str
    df: pd.DataFrame
    digest: str # résumé compact du vrac (audit_scan) — préfixe stable
    created_at: float
    last_used: float
    # Rapport d'audit du projet (AUD-001), injecté en contexte optionnel du
    # system prompt (0.6.0). None = exploration « à froid » (prompt inchangé).
    # Figé à la création : changer le toggle côté front recrée la session.
    audit_report: str | None = None
    # Historique compact du dialogue (messages user/assistant, sans le trafic
    # d'outils) : le contexte des tours suivants, borné par l'agent.
    history: list[dict] = field(default_factory=list)
    # Tokens cumulés de la session : sommés à chaque tour, affichés par l'UI.
    usage_total: dict = field(default_factory=dict)
    # Coût € indicatif cumulé : None tant qu'aucun tour n'a de tarif connu
    # (modèle local ou cloud hors grille `core.pricing` → rien à afficher).
    cost_eur: float | None = None


class SessionStore:
    """Magasin de sessions en mémoire process, borné et à TTL.

    Thread-safe (l'API FastAPI itère les générateurs SSE dans un threadpool).
    L'horloge est injectable (`now`) pour des tests d'expiration déterministes.
    """

    def __init__(
        self,
        ttl_s: int = DEFAULT_TTL_S,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        now: Callable[[], float] = time.monotonic,
    ):
        self.ttl_s = ttl_s
        self.max_sessions = max_sessions
        self._now = now
        self._lock = threading.Lock()
        self._sessions: dict[str, AgentSession] = {}

    def create(
        self, df: pd.DataFrame, digest: str, audit_report: str | None = None
    ) -> AgentSession:
        with self._lock:
            self._evict_locked()
            t = self._now()
            session = AgentSession(
                session_id=uuid.uuid4().hex,
                df=df,
                digest=digest,
                created_at=t,
                last_used=t,
                audit_report=audit_report,
            )
            # Au plafond malgré l'éviction des expirées : on écarte la moins
            # récemment utilisée (cache de travail, jamais la seule copie).
            while len(self._sessions) >= self.max_sessions:
                lru = min(self._sessions.values(), key=lambda s: s.last_used)
                del self._sessions[lru.session_id]
            self._sessions[session.session_id] = session
            return session

    def get(self, session_id: str) -> AgentSession:
        with self._lock:
            self._evict_locked()
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFound(session_id)
            session.last_used = self._now()
            return session

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def status(self, session_id: str) -> dict:
        """État d'une session (pour l'UI) — lève SessionNotFound si absente."""
        session = self.get(session_id)
        t = self._now()
        return {
            "sessionId": session.session_id,
            "rows": int(len(session.df)),
            "ageS": round(t - session.created_at),
            "expiresInS": max(0, round(self.ttl_s - (t - session.last_used))),
            "turns": sum(1 for m in session.history if m.get("role") == "user"),
            "usageTotal": session.usage_total or None,
            "costEur": round(session.cost_eur, 4) if session.cost_eur is not None else None,
        }

    def _evict_locked(self) -> None:
        deadline = self._now() - self.ttl_s
        expired = [sid for sid, s in self._sessions.items() if s.last_used < deadline]
        for sid in expired:
            del self._sessions[sid]


# Magasin par défaut du process (consommé par l'API) — mono-poste par design.
STORE = SessionStore()


def add_usage(session: AgentSession, usage: dict | None) -> None:
    """Cumule l'usage tokens d'un appel LLM dans la session."""
    if not usage:
        return
    total = session.usage_total
    for key, value in usage.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total[key] = (total.get(key) or 0) + value
