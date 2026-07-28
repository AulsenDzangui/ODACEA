"""Retry automatique sur erreurs transitoires (`llm.litellm_provider`).

`litellm.completion` est mocké : aucun appel réseau. On vérifie la politique :
retry sur transitoire avant le premier chunk uniquement, backoff visible via
`on_retry`, jamais de retry sur erreur de contenu ni après début de réponse.
"""
from types import SimpleNamespace

import pytest

import llm.litellm_provider as lp
from llm.litellm_provider import RETRY_DELAYS, LiteLLMProvider, _is_transient_error


def _chunk(content: str):
    return SimpleNamespace(
        usage=None,
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, thinking=None,
                                                       reasoning_content=None))],
    )


class _TransientError(Exception):
    status_code = 503


class _ContentError(Exception):
    status_code = 401


@pytest.fixture
def no_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(lp.time, "sleep", slept.append)
    return slept


def _provider():
    return LiteLLMProvider(model="openai/test", base_url="http://localhost:1234/v1")


def _mock_completion(monkeypatch, behaviours):
    """`behaviours` : liste d'éléments — soit une Exception (levée au premier
    next), soit une liste de chunks à streamer. Un élément par appel."""
    calls = {"n": 0}

    def fake_completion(**kwargs):
        b = behaviours[calls["n"]]
        calls["n"] += 1
        if isinstance(b, Exception):
            raise b
        def gen():
            for item in b:
                if isinstance(item, Exception):
                    raise item
                yield item
        return gen()

    monkeypatch.setattr(lp, "completion", fake_completion)
    return calls


def test_transient_error_retried_then_succeeds(monkeypatch, no_sleep):
    calls = _mock_completion(monkeypatch, [
        _TransientError("indispo"),
        [_chunk("ok-"), _chunk("fin")],
    ])
    p = _provider()
    notices: list[str] = []
    p.on_retry = notices.append

    out = list(p.stream_with_reasoning("sys", "user"))

    assert [c for _, c in out] == ["ok-", "fin"]
    assert calls["n"] == 2
    assert p.last_retries == 1
    assert no_sleep == [RETRY_DELAYS[0]]
    assert len(notices) == 1 and "tentative 1/2" in notices[0]


def test_retries_exhausted_raises(monkeypatch, no_sleep):
    calls = _mock_completion(
        monkeypatch, [_TransientError("a"), _TransientError("b"), _TransientError("c")]
    )
    p = _provider()
    with pytest.raises(_TransientError):
        list(p.stream_with_reasoning("sys", "user"))
    assert calls["n"] == len(RETRY_DELAYS) + 1
    assert no_sleep == list(RETRY_DELAYS)


def test_content_error_never_retried(monkeypatch, no_sleep):
    calls = _mock_completion(monkeypatch, [_ContentError("clé invalide")])
    p = _provider()
    with pytest.raises(_ContentError):
        list(p.stream_with_reasoning("sys", "user"))
    assert calls["n"] == 1
    assert no_sleep == []


def test_error_after_first_chunk_not_retried(monkeypatch, no_sleep):
    """Réponse entamée : pas de retry (la dupliquer corromprait la sortie)."""
    calls = _mock_completion(
        monkeypatch, [[_chunk("début"), _TransientError("coupé")]]
    )
    p = _provider()
    received = []
    with pytest.raises(_TransientError):
        for item in p.stream_with_reasoning("sys", "user"):
            received.append(item)
    assert calls["n"] == 1
    assert received == [(False, "début")]
    assert no_sleep == []


def test_is_transient_classification():
    assert _is_transient_error(_TransientError("x"))

    class Err429(Exception):
        status_code = 429

    class Err400(Exception):
        status_code = 400

    assert _is_transient_error(Err429("rate"))
    assert not _is_transient_error(Err400("bad"))
    assert not _is_transient_error(ValueError("contenu"))
