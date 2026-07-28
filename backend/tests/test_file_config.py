"""Tests du fichier de configuration `odacea.toml`.

Couvre la lecture/validation (`config.file_config`), la découverte du fichier et
la résolution dans la CLI (précédence CLI > config > défauts intégrés).
"""
from __future__ import annotations

import pytest

import cli
from config.file_config import (
    ConfigError,
    discover_config,
    load_config,
    section_get,
)

# ── Lecture / validation du fichier ──────────────────────────────────────────

def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_keeps_known_keys(tmp_path):
    cfg_path = _write(tmp_path / "odacea.toml", """
[llm]
model = "m1"
base_url = "http://localhost:1234/v1"

[prep]
filter_columns = false
sample_n = 12
description = true

[classement]
batch_size = 25
avis = false
ref = true
""")
    config, warnings = load_config(cfg_path)
    assert warnings == []
    assert section_get(config, "llm", "model") == "m1"
    assert section_get(config, "prep", "filter_columns") is False
    assert section_get(config, "prep", "sample_n") == 12
    assert section_get(config, "classement", "ref") is True


def test_load_config_warns_on_unknown_keys(tmp_path):
    cfg_path = _write(tmp_path / "odacea.toml", """
[llm]
model = "m1"
typo_key = "x"

[inconnue]
foo = 1
""")
    config, warnings = load_config(cfg_path)
    assert section_get(config, "llm", "model") == "m1"
    # La coquille est signalée mais non bloquante.
    assert any("typo_key" in w for w in warnings)
    assert any("inconnue" in w for w in warnings)
    assert "inconnue" not in config


def test_load_config_rejects_wrong_type(tmp_path):
    cfg_path = _write(tmp_path / "odacea.toml", '[prep]\nsample_n = "douze"\n')
    with pytest.raises(ConfigError, match="sample_n"):
        load_config(cfg_path)


def test_load_config_rejects_bool_for_int(tmp_path):
    # bool est une sous-classe d'int : on ne doit pas l'accepter pour sample_n.
    cfg_path = _write(tmp_path / "odacea.toml", "[prep]\nsample_n = true\n")
    with pytest.raises(ConfigError, match="sample_n"):
        load_config(cfg_path)


def test_load_config_rejects_malformed_toml(tmp_path):
    cfg_path = _write(tmp_path / "odacea.toml", "[llm\nmodel = ")
    with pytest.raises(ConfigError, match="TOML invalide"):
        load_config(cfg_path)


# ── Découverte du fichier ────────────────────────────────────────────────────

def test_discover_explicit_missing_raises():
    with pytest.raises(ConfigError, match="introuvable"):
        discover_config("/chemin/inexistant/odacea.toml")


def test_discover_walks_up_from_cwd(tmp_path):
    _write(tmp_path / "odacea.toml", "[llm]\nmodel = 'm'\n")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    found = discover_config(None, start=sub)
    assert found == tmp_path / "odacea.toml"


def test_discover_returns_none_when_absent(tmp_path):
    assert discover_config(None, start=tmp_path) is None


# ── Résolution dans la CLI (précédence CLI > config > défaut) ─────────────────

def _parse_and_resolve(argv):
    args = cli.build_parser().parse_args(argv)
    cli._apply_file_config(args)
    return args


def test_config_supplies_defaults(tmp_path):
    cfg = _write(tmp_path / "odacea.toml", """
[llm]
model = "config-model"
base_url = "http://srv:1234/v1"

[prep]
filter_columns = false
sample_n = 9
description = true

[classement]
batch_size = 30
avis = false
ref = true
""")
    a = _parse_and_resolve(
        ["classement", "x.csv", "--plan", "p.md", "--out", "o.csv", "--config", str(cfg)]
    )
    assert a.model == "config-model"
    assert a.base_url == "http://srv:1234/v1"
    assert a.batch_size == 30
    assert a.ref is True
    assert a.no_avis is True  # avis = false → bloc avis désactivé
    assert a.description is True


def test_config_concurrency_default_and_override(tmp_path):
    cfg = _write(tmp_path / "odacea.toml", "[classement]\nconcurrency = 3\n")
    # Sans flag CLI : la config fournit la valeur.
    a = _parse_and_resolve(
        ["classement", "x.csv", "--plan", "p.md", "--out", "o.csv", "--config", str(cfg)]
    )
    assert a.concurrency == 3
    # Le flag CLI prime sur la config.
    b = _parse_and_resolve([
        "classement", "x.csv", "--plan", "p.md", "--out", "o.csv",
        "--config", str(cfg), "--concurrency", "2",
    ])
    assert b.concurrency == 2
    # Sans config ni flag : défaut intégré = séquentiel (1).
    c = cli.build_parser().parse_args(["classement", "x.csv", "--plan", "p.md", "--out", "o.csv"])
    cli._resolve_config_into_args(c, {})
    assert c.concurrency == 1


def test_cli_overrides_config(tmp_path):
    cfg = _write(tmp_path / "odacea.toml", """
[llm]
model = "config-model"

[classement]
batch_size = 30
ref = true
""")
    a = _parse_and_resolve([
        "classement", "x.csv", "--plan", "p.md", "--out", "o.csv",
        "--config", str(cfg), "--model", "cli-model", "--batch-size", "7",
    ])
    assert a.model == "cli-model"
    assert a.batch_size == 7
    # `ref` non passé en CLI → la config s'applique encore.
    assert a.ref is True


def test_config_negated_prep_flag(tmp_path):
    cfg = _write(tmp_path / "odacea.toml", "[prep]\nfilter_columns = false\nsample_n = 3\n")
    a = _parse_and_resolve(["audit", "x.csv", "--config", str(cfg)])
    assert a.no_filter_columns is True  # filter_columns=false → --no-filter-columns implicite
    assert a.sample_n == 3
    # Une option non touchée par la config garde son défaut intégré.
    assert a.no_clean_dates is False


def test_no_config_uses_builtin_defaults(tmp_path):
    # start hors de toute hiérarchie contenant odacea.toml → résolution = défauts.
    a = cli.build_parser().parse_args(["audit", "x.csv"])
    # Simule l'absence de fichier en pointant la découverte sur un dossier vide.
    cli._resolve_config_into_args(a, {})
    assert a.no_filter_columns is False
    assert a.sample_n == 5
    assert a.description is False
    assert a.model is None


def test_invalid_config_exits_config_error(tmp_path):
    cfg = _write(tmp_path / "odacea.toml", "[prep]\nsample_n = 'oops'\n")
    with pytest.raises(SystemExit) as exc:
        _parse_and_resolve(["audit", "x.csv", "--config", str(cfg)])
    assert exc.value.code == cli.EXIT_CONFIG_ERROR


def test_config_model_drives_run_without_cli_flag(tmp_path, monkeypatch, golden_aud):
    """Bout-en-bout : un audit sans `--model` utilise le modèle du fichier de
    config (sinon EXIT_CONFIG_ERROR faute de modèle)."""
    from tests.conftest import FakeProvider, load_fixture

    input_csv = _write(tmp_path / "vrac.csv", load_fixture("archifiltre_small.csv"))
    cfg = _write(tmp_path / "odacea.toml", "[llm]\nmodel = 'config-model'\n")

    seen = {}
    monkeypatch.setattr(cli, "DEFAULT_MODEL", "")  # aucun modèle via .env

    def _fake_get_provider(**kw):
        seen["model"] = kw.get("model")
        return FakeProvider(response=golden_aud)

    monkeypatch.setattr(cli, "get_provider", _fake_get_provider)
    rc = cli.main([
        "audit", str(input_csv), "--config", str(cfg),
        "--out-plan", str(tmp_path / "plan.md"),
    ])
    assert rc == cli.EXIT_OK
    assert seen["model"] == "config-model"


def test_eval_model_list_not_clobbered_by_config(tmp_path):
    # eval `--model` est répétable (liste) : une valeur unique de config ne doit
    # pas l'écraser. base_url (valeur simple) reste surchargeable.
    cfg = _write(tmp_path / "odacea.toml", "[llm]\nmodel = 'cfg'\nbase_url = 'http://h/v1'\n")
    a = _parse_and_resolve([
        "eval", "--input", "x.csv", "--model", "m1", "--model", "m2", "--config", str(cfg),
    ])
    assert a.model == ["m1", "m2"]
    assert a.base_url == "http://h/v1"
