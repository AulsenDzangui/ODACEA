"""Durcissement démo — vérification des quotas `api/demo_limits.py` **sous
charge concurrente**.

Le limiteur est transactionnel (`begin`/`commit`/`rollback`) sous un verrou
global : la réservation atomique à l'entrée ferme la fenêtre TOCTOU. On le prouve
ici en faisant courir de nombreux threads simultanés :

  * un seul visiteur (même IP) ne dépasse jamais ``MAX_TRIES_PER_STAGE`` essais,
    même si toutes ses requêtes arrivent en rafale ;
  * le plafond global de tokens n'est jamais dépassé de plus d'une réservation en
    vol par appel concurrent.
"""
import threading

import pytest

from api import demo_limits


@pytest.fixture(autouse=True)
def _reset_demo_state():
    """Repart d'un compteur vierge (état module éphémère) avant chaque test."""
    with demo_limits._lock:
        demo_limits._day = demo_limits._today()
        demo_limits._ip_usage = {}
        demo_limits._tokens_today = 0
    yield


def _race(targets):
    """Lance tous les workers au même instant (Barrier) et attend la fin."""
    barrier = threading.Barrier(len(targets))

    def runner(fn):
        barrier.wait()
        fn()

    threads = [threading.Thread(target=runner, args=(t,)) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def test_per_ip_try_cap_holds_under_concurrency():
    """Même IP/étape, 50 requêtes en rafale : exactement MAX_TRIES passent."""
    n = 50
    successes: list[demo_limits.Reservation] = []
    refusals: list[int] = []
    lock = threading.Lock()

    def attempt():
        try:
            res = demo_limits.begin("203.0.113.7", "audit")
            with lock:
                successes.append(res)
        except demo_limits.DemoLimitError:
            with lock:
                refusals.append(1)

    _race([attempt] * n)

    assert len(successes) == demo_limits.MAX_TRIES_PER_STAGE
    assert len(refusals) == n - demo_limits.MAX_TRIES_PER_STAGE


def test_per_ip_cap_is_per_stage():
    """Le quota d'une étape ne consomme pas celui de l'autre."""
    for _ in range(demo_limits.MAX_TRIES_PER_STAGE):
        demo_limits.begin("198.51.100.1", "audit")
    with pytest.raises(demo_limits.DemoLimitError):
        demo_limits.begin("198.51.100.1", "audit")
    # « classement » reste disponible pour la même IP.
    res = demo_limits.begin("198.51.100.1", "classement")
    assert res.stage == "classement"


def test_global_token_cap_holds_under_concurrency():
    """100 IP distinctes en rafale : le plafond global n'est jamais dépassé de
    plus d'une réservation en vol (garantie TOCTOU)."""
    n = 100
    successes: list[demo_limits.Reservation] = []
    lock = threading.Lock()

    def attempt(i: int):
        try:
            res = demo_limits.begin(f"192.0.2.{i}", "audit")
            with lock:
                successes.append(res)
        except demo_limits.DemoLimitError:
            pass

    _race([lambda i=i: attempt(i) for i in range(n)])

    snap = demo_limits.snapshot()
    # Plafond atteint mais jamais dépassé au-delà d'une réservation par appel.
    assert snap["tokensToday"] <= demo_limits.DAILY_TOKEN_CAP + demo_limits.RESERVE_TOKENS
    assert snap["tokensToday"] >= demo_limits.DAILY_TOKEN_CAP - demo_limits.RESERVE_TOKENS
    # Toutes les requêtes n'ont pas pu passer (le cap a bien mordu).
    assert len(successes) < n
    # Cohérence : tokens réservés == somme des réservations accordées.
    assert snap["tokensToday"] == sum(r.reserved_tokens for r in successes)


def test_rollback_frees_try_and_tokens_concurrently():
    """Un échec (rollback) rend l'essai et les tokens : sous charge, l'essai
    rendu est réutilisable par la requête concurrente suivante."""
    res = demo_limits.begin("198.51.100.9", "classement")
    before = demo_limits.snapshot()["tokensToday"]
    demo_limits.rollback(res)
    after = demo_limits.snapshot()["tokensToday"]
    assert after == before - res.reserved_tokens
    # L'essai a été rendu : on peut de nouveau réserver MAX_TRIES fois.
    for _ in range(demo_limits.MAX_TRIES_PER_STAGE):
        demo_limits.begin("198.51.100.9", "classement")


def test_commit_reconciles_to_actual_usage():
    """Le commit remplace les tokens provisionnés par l'usage réel."""
    res = demo_limits.begin("198.51.100.20", "audit")
    demo_limits.commit(res, actual_tokens=1234)
    assert demo_limits.snapshot()["tokensToday"] == 1234
