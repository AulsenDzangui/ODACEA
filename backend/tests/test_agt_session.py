"""Sessions de travail de l'agent — TTL, éviction, cumul d'usage.

L'horloge du magasin est injectée : l'expiration se teste sans attendre. La
reconstruction est vérifiée côté API (`test_agt_api`) : une session
expirée renvoie un code stable que le front traite en recréant la session
depuis son projet (le CSV client reste la seule copie durable).
"""
import pytest

from core.agt_session import SessionNotFound, SessionStore, add_usage


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock) -> SessionStore:
    return SessionStore(ttl_s=100, max_sessions=2, now=clock)


def test_create_get_roundtrip(store, small_df):
    session = store.create(small_df, "digest")
    assert store.get(session.session_id) is session
    assert session.digest == "digest"
    assert len(session.df) == 10
    # Rapport d'audit optionnel (0.6.0) : None par défaut.
    assert session.audit_report is None


def test_create_avec_rapport_audit(store, small_df):
    """Le rapport d'audit fourni est conservé sur la session (contexte 0.6.0)."""
    session = store.create(small_df, "digest", audit_report="RAPPORT")
    assert store.get(session.session_id).audit_report == "RAPPORT"


def test_session_inconnue(store):
    with pytest.raises(SessionNotFound):
        store.get("inexistante")


def test_ttl_expiration(store, clock, small_df):
    session = store.create(small_df, "d")
    clock.t = 99
    store.get(session.session_id)  # toujours vivante (et re-touchée)
    clock.t = 300
    with pytest.raises(SessionNotFound):
        store.get(session.session_id)


def test_acces_repousse_le_ttl(store, clock, small_df):
    """`get` touche la session : l'expiration court depuis le dernier usage."""
    session = store.create(small_df, "d")
    clock.t = 90
    store.get(session.session_id)
    clock.t = 180  # 90 s après le dernier usage < TTL 100
    assert store.get(session.session_id) is session


def test_eviction_lru_au_plafond(store, clock, small_df):
    """Au plafond, la session la moins récemment utilisée est écartée (cache de
    travail : jamais la seule copie, le client peut la recréer)."""
    s1 = store.create(small_df, "d")
    clock.t = 1
    s2 = store.create(small_df, "d")
    clock.t = 2
    store.get(s1.session_id)  # s2 devient la moins récemment utilisée
    clock.t = 3
    s3 = store.create(small_df, "d")
    assert store.get(s1.session_id) is s1
    assert store.get(s3.session_id) is s3
    with pytest.raises(SessionNotFound):
        store.get(s2.session_id)


def test_delete(store, small_df):
    session = store.create(small_df, "d")
    assert store.delete(session.session_id) is True
    assert store.delete(session.session_id) is False


def test_status(store, clock, small_df):
    session = store.create(small_df, "d")
    session.history += [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "r1"},
    ]
    clock.t = 40
    status = store.status(session.session_id)
    assert status["rows"] == 10
    assert status["ageS"] == 40
    assert status["expiresInS"] == 100  # get() vient de toucher la session
    assert status["turns"] == 1
    assert status["usageTotal"] is None


def test_add_usage_cumule(store, small_df):
    """Les tokens de chaque appel s'additionnent sur la session ; les
    champs absents (None) n'écrasent rien."""
    session = store.create(small_df, "d")
    add_usage(session, {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": None})
    add_usage(session, {"input_tokens": 50, "output_tokens": 5, "total_tokens": 55})
    add_usage(session, None)
    assert session.usage_total == {"input_tokens": 150, "output_tokens": 25, "total_tokens": 55}
