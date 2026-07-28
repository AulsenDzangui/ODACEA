"""Cache de prompt Anthropic (`llm.litellm_provider`).

`litellm.completion` est mocké : aucun appel réseau. On vérifie la construction
des messages — `cache_control` marqué sur le system prompt et le préfixe stable
(plan) du user message **uniquement** pour Anthropic en direct ; messages en
chaînes simples (comportement historique) pour tout autre fournisseur ou serveur
local.
"""
from types import SimpleNamespace

import pytest

import llm.litellm_provider as lp
from llm.litellm_provider import LiteLLMProvider
from prompts import CLA_001

_EPHEMERAL = {"type": "ephemeral"}


def _anthropic(model="claude-opus-4-8"):
    return LiteLLMProvider(model=model)


# ── _build_messages : Anthropic ──────────────────────────────────────────────


def test_anthropic_system_marked_cacheable():
    msgs = _anthropic()._build_messages("SYS", "USER")
    system = msgs[0]
    assert system["role"] == "system"
    assert system["content"] == [
        {"type": "text", "text": "SYS", "cache_control": _EPHEMERAL}
    ]


def test_anthropic_no_boundary_user_stays_plain():
    msgs = _anthropic()._build_messages("SYS", "USER", None)
    assert msgs[1] == {"role": "user", "content": "USER"}


def test_anthropic_boundary_splits_user_into_cached_prefix():
    user = "PLAN-stable\n\n--SEP--\nlot variable"
    msgs = _anthropic()._build_messages("SYS", user, "--SEP--")
    content = msgs[1]["content"]
    assert content == [
        {"type": "text", "text": "PLAN-stable\n\n", "cache_control": _EPHEMERAL},
        {"type": "text", "text": "--SEP--\nlot variable"},
    ]


def test_anthropic_prefix_only_via_anthropic_slash():
    msgs = _anthropic(model="anthropic/claude-3-5-sonnet")._build_messages("SYS", "U")
    assert isinstance(msgs[0]["content"], list)
    assert msgs[0]["content"][0]["cache_control"] == _EPHEMERAL


def test_boundary_absent_user_stays_plain():
    msgs = _anthropic()._build_messages("SYS", "no marker here", "--SEP--")
    assert msgs[1]["content"] == "no marker here"


def test_boundary_at_start_no_split():
    # Préfixe vide → rien à cacher côté user.
    msgs = _anthropic()._build_messages("SYS", "--SEP--reste", "--SEP--")
    assert msgs[1]["content"] == "--SEP--reste"


# ── _build_messages : autres fournisseurs (comportement historique) ──────────


@pytest.mark.parametrize("model", ["gpt-5.1", "gemini/gemini-2.0", "ollama/qwen3:14b"])
def test_non_anthropic_plain_strings(model):
    msgs = LiteLLMProvider(model=model)._build_messages("SYS", "USER", "USER")
    assert msgs == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]


def test_local_base_url_never_cached_even_if_claude_named():
    # Un serveur local (base_url) ne comprend pas cache_control : chaînes simples.
    p = LiteLLMProvider(model="claude-proxy", base_url="http://localhost:1234/v1")
    msgs = p._build_messages("SYS", "PLAN\n\n--SEP--\nlot", "--SEP--")
    assert msgs == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "PLAN\n\n--SEP--\nlot"},
    ]


# ── Frontière réelle CLA-001 ─────────────────────────────────────────────────


def test_cla_real_user_message_splits_plan_from_items():
    user = CLA_001.build_user_message(
        csv_content="Path;CurrentTitle;Date\na\\b.pdf;b.pdf;2020-01-01",
        plan_valide="# Plan\n1_Dossier\n",
    )
    msgs = _anthropic()._build_messages("SYS", user, CLA_001.CACHE_BOUNDARY)
    cached, rest = msgs[1]["content"]
    # Le préfixe cacheable porte le plan, pas la liste des fichiers.
    assert "Plan de classement validé" in cached["text"]
    assert "1_Dossier" in cached["text"]
    assert "b.pdf" not in cached["text"]
    assert cached["cache_control"] == _EPHEMERAL
    # Le reste (variable d'un lot à l'autre) porte les fichiers, sans cache.
    assert rest["text"].startswith(CLA_001.CACHE_BOUNDARY)
    assert "b.pdf" in rest["text"]
    assert "cache_control" not in rest


def test_cla_boundary_text_unchanged_in_message():
    # La frontière reste le texte littéral du prompt (pas de modification de contenu).
    user = CLA_001.build_user_message(csv_content="x", plan_valide="p")
    assert CLA_001.CACHE_BOUNDARY in user


# ── Intégration : les messages cachés atteignent completion ──────────────────


def _chunk(content):
    return SimpleNamespace(
        usage=None,
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content, thinking=None,
                                                        reasoning_content=None))],
    )


def test_cache_control_reaches_completion_call(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        def gen():
            yield _chunk("ok")
        return gen()

    monkeypatch.setattr(lp, "completion", fake_completion)
    p = _anthropic()
    list(p.stream_with_reasoning("SYS", "PLAN\n\n--SEP--\nlot", cache_user_boundary="--SEP--"))

    msgs = captured["messages"]
    assert msgs[0]["content"][0]["cache_control"] == _EPHEMERAL
    assert msgs[1]["content"][0]["cache_control"] == _EPHEMERAL
