"""Câblage de `--corrections` dans le harnais d'éval (`cli.py eval`).

Permet de mesurer l'apport du few-shot des corrections (expérience (a)) par
deux runs d'éval — un avec, un sans le flag — dont on compare les métriques. Le
*câblage* (injection effective du bloc dans le prompt CLA-001) est testé **sans
LLM** via une doublure de provider qui capture les messages.
"""
from __future__ import annotations

import pytest

import cli
from tests.conftest import FakeProvider, load_fixture

EXAMPLES_MARKER = "Exemples de classements déjà validés"


@pytest.fixture
def corpus(tmp_path):
    path = tmp_path / "vrac.csv"
    path.write_text(load_fixture("archifiltre_small.csv"), encoding="utf-8")
    return path


@pytest.fixture
def plan_md(tmp_path, plan_valide):
    path = tmp_path / "plan.md"
    path.write_text(plan_valide, encoding="utf-8")
    return path


@pytest.fixture
def corrections_csv(tmp_path):
    path = tmp_path / "corrections.csv"
    path.write_text(
        "Path;TargetFolder;NewTitle\n"
        "inscriptions/liste_eleves_2022.xlsx;1_Inscriptions;2022_liste.xlsx\n"
        "cantine/menus_janvier.docx;2-1_Menus;2022_menus.docx\n",
        encoding="utf-8",
    )
    return path


def _run_eval(monkeypatch, tmp_path, provider, extra_args):
    monkeypatch.setattr(cli, "get_provider", lambda **kw: provider)
    argv = [
        "eval", "--input", str(extra_args.pop("corpus")),
        "--model", "fake-model", "--agent", "cla",
        "--plan", str(extra_args.pop("plan")),
        "--cla-mode", "path", "--no-save",
        *extra_args.pop("rest", []),
    ]
    return cli.main(argv)


def test_eval_corrections_injects_examples(
    monkeypatch, tmp_path, corpus, plan_md, corrections_csv, golden_cla_path
):
    provider = FakeProvider(response=golden_cla_path)
    code = _run_eval(
        monkeypatch, tmp_path, provider,
        {"corpus": corpus, "plan": plan_md,
         "rest": ["--corrections", str(corrections_csv)]},
    )
    assert code == 0
    # Le bloc few-shot est présent dans le user message ET la consigne d'usage
    # dans le system prompt.
    system_prompt, user_message = provider.calls[-1]
    assert EXAMPLES_MARKER in user_message
    assert "1_Inscriptions" in user_message


def test_eval_without_corrections_leaves_prompt_clean(
    monkeypatch, tmp_path, corpus, plan_md, golden_cla_path
):
    provider = FakeProvider(response=golden_cla_path)
    code = _run_eval(
        monkeypatch, tmp_path, provider,
        {"corpus": corpus, "plan": plan_md, "rest": []},
    )
    assert code == 0
    _, user_message = provider.calls[-1]
    assert EXAMPLES_MARKER not in user_message


def test_eval_corrections_missing_file_is_rejected(
    monkeypatch, tmp_path, corpus, plan_md
):
    provider = FakeProvider(response="```csv\nPath;TargetFolder;NewTitle\n```")
    code = _run_eval(
        monkeypatch, tmp_path, provider,
        {"corpus": corpus, "plan": plan_md,
         "rest": ["--corrections", str(tmp_path / "absent.csv")]},
    )
    assert code == cli.EXIT_INPUT_INVALID
    # Aucun appel LLM : la garde tombe avant la matrice.
    assert provider.calls == []
