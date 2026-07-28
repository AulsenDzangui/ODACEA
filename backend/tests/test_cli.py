"""Tests bout-en-bout de l'interface batch (`cli.py`) — B3 (+ reprise).

Provider LLM mocké (FakeProvider/SequenceProvider rejouant les golden files) :
codes de sortie EXIT_*, fichiers produits, modes --ref et --batch-size,
artefacts bruts et reprise --resume sans repayer les lots réussis.
"""

import argparse
import json
from pathlib import Path

import pytest

import cli
from core.csv_handler import extract_csv_from_response, read_csv
from tests.conftest import FakeProvider, SequenceProvider, load_fixture


@pytest.fixture
def input_csv(tmp_path):
    path = tmp_path / "vrac.csv"
    path.write_text(load_fixture("archifiltre_small.csv"), encoding="utf-8")
    return path


@pytest.fixture
def plan_file(tmp_path, plan_valide):
    path = tmp_path / "plan.md"
    path.write_text(plan_valide, encoding="utf-8")
    return path


def _use_provider(monkeypatch, provider):
    monkeypatch.setattr(cli, "get_provider", lambda **kw: provider)
    return provider


def _read_out_csv(path):
    with open(path, "rb") as f:
        return read_csv(f)


def _batch_response(df_slice):
    body = "\n".join(";".join(map(str, row)) for row in df_slice.values)
    return f"```csv\nPath;TargetFolder;NewTitle\n{body}\n```"


# ── audit ────────────────────────────────────────────────────────────────────

def test_audit_writes_report_plan_notes(monkeypatch, tmp_path, input_csv, golden_aud):
    _use_provider(monkeypatch, FakeProvider(response=golden_aud))
    rc = cli.main([
        "audit", str(input_csv),
        "--out-report", str(tmp_path / "rapport.md"),
        "--out-plan", str(tmp_path / "plan.md"),
        "--out-notes", str(tmp_path / "notes.md"),
        "--model", "test-model",
    ])
    assert rc == cli.EXIT_OK
    assert (tmp_path / "rapport.md").read_text(encoding="utf-8") == golden_aud
    plan = (tmp_path / "plan.md").read_text(encoding="utf-8")
    assert "AFFAIRES_SCOLAIRES/" in plan and "PARTIE 1" not in plan
    assert "RGPD" in (tmp_path / "notes.md").read_text(encoding="utf-8")


def test_audit_missing_input_exits_2(monkeypatch, tmp_path):
    _use_provider(monkeypatch, FakeProvider())
    with pytest.raises(SystemExit) as exc:
        cli.main(["audit", str(tmp_path / "absent.csv"), "--model", "m"])
    assert exc.value.code == cli.EXIT_INPUT_INVALID


def test_audit_invalid_csv_exits_2(monkeypatch, tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("Colonne1;Colonne2\na;b\n", encoding="utf-8")
    _use_provider(monkeypatch, FakeProvider())
    with pytest.raises(SystemExit) as exc:
        cli.main(["audit", str(bad), "--model", "m"])
    assert exc.value.code == cli.EXIT_INPUT_INVALID


def test_audit_no_model_exits_4(monkeypatch, input_csv):
    monkeypatch.setattr(cli, "DEFAULT_MODEL", "")
    with pytest.raises(SystemExit) as exc:
        cli.main(["audit", str(input_csv)])
    assert exc.value.code == cli.EXIT_CONFIG_ERROR


def test_audit_llm_error_exits_1(monkeypatch, input_csv):
    provider = FakeProvider()
    provider.failures = [RuntimeError("connexion coupée")]
    _use_provider(monkeypatch, provider)
    with pytest.raises(SystemExit) as exc:
        cli.main(["audit", str(input_csv), "--model", "m"])
    assert exc.value.code == cli.EXIT_LLM_ERROR


# ── audit comparatif multi-plans ──────────────────────────────────────────────

def _aud_response(*folders):
    """Réponse AUD-001 minimale portant un plan avec l'arbre technique donné."""
    body = "\n".join(f"{f}/" for f in folders)
    return (
        "# Rapport d'audit\n\n## PARTIE 2 — PLAN DE CLASSEMENT\n\n"
        "Arborescence technique\n"
        f"<!-- PLAN_STRUCTURE_START -->\n{body}\n<!-- PLAN_STRUCTURE_END -->\n"
    )


def test_audit_variants_runs_n_times_and_compares(monkeypatch, tmp_path, input_csv):
    responses = [
        _aud_response("1_Inscriptions", "2_Cantine", "2-1_Menus"),
        _aud_response("1_Cantine", "1-1_Menus", "2_Vie_scolaire"),
    ]
    provider = _use_provider(monkeypatch, SequenceProvider(responses))
    out_dir = tmp_path / "variantes"
    rc = cli.main([
        "audit", str(input_csv), "--variants", "2",
        "--out-dir", str(out_dir), "--model", "m", "--brief",
    ])
    assert rc == cli.EXIT_OK
    assert len(provider.calls) == 2  # un appel LLM par variante
    # Chaque variante écrite séparément + une comparaison.
    assert (out_dir / "variante-1_plan.md").is_file()
    assert (out_dir / "variante-2_rapport.md").is_file()
    comp = json.loads((out_dir / "comparaison.json").read_text(encoding="utf-8"))
    assert comp["comparison"]["identical"] is False
    assert "cantine" in comp["comparison"]["commonFolders"]


def test_audit_variants_json_payload(monkeypatch, tmp_path, input_csv, capsys):
    responses = [
        _aud_response("1_Inscriptions", "2_Cantine"),
        _aud_response("1_Inscriptions", "2_Cantine"),
    ]
    _use_provider(monkeypatch, SequenceProvider(responses))
    rc = cli.main([
        "audit", str(input_csv), "--variants", "2", "--model", "m", "--json",
    ])
    assert rc == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "audit"
    assert len(payload["variants"]) == 2
    assert payload["variants"][0]["index"] == 1
    assert "metrics" in payload["variants"][0]
    # Deux plans identiques → comparaison « identique ».
    assert payload["comparison"]["identical"] is True
    assert payload["comparison"]["variantCount"] == 2


def test_audit_variants_one_keeps_simple_path(monkeypatch, tmp_path, input_csv, golden_aud):
    """--variants 1 = audit simple : résumé classique, aucune comparaison."""
    _use_provider(monkeypatch, FakeProvider(response=golden_aud))
    rc = cli.main([
        "audit", str(input_csv), "--variants", "1",
        "--out-report", str(tmp_path / "rapport.md"), "--model", "m", "--json",
    ])
    assert rc == cli.EXIT_OK
    assert (tmp_path / "rapport.md").is_file()


def test_audit_variants_invalid_count_exits_2(monkeypatch, input_csv):
    _use_provider(monkeypatch, FakeProvider())
    with pytest.raises(SystemExit) as exc:
        cli.main(["audit", str(input_csv), "--variants", "0", "--model", "m"])
    assert exc.value.code == cli.EXIT_INPUT_INVALID


def test_audit_variants_clamped_to_max(monkeypatch, input_csv, capsys):
    responses = [_aud_response("1_A") for _ in range(cli.MAX_VARIANTS)]
    provider = _use_provider(monkeypatch, SequenceProvider(responses))
    rc = cli.main([
        "audit", str(input_csv), "--variants", str(cli.MAX_VARIANTS + 3), "--model", "m",
    ])
    assert rc == cli.EXIT_OK
    assert len(provider.calls) == cli.MAX_VARIANTS  # borné au maximum
    assert "maximum" in capsys.readouterr().err


# ── classement ───────────────────────────────────────────────────────────────

def test_classement_path_mode_produces_resip(monkeypatch, tmp_path, input_csv,
                                             plan_file, golden_cla_path):
    provider = _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m",
    ])
    assert rc == cli.EXIT_OK
    df = _read_out_csv(out)
    assert (df["Content.DescriptionLevel"] == "Item").sum() == 6
    assert (df["File"] == ".").sum() == 1
    # Mode Path (défaut) : l'identifiant en entrée est le chemin, pas la Ref.
    user_msg = provider.calls[-1][1]
    assert "Path;CurrentTitle;Date" in user_msg


def test_classement_ref_mode(monkeypatch, tmp_path, input_csv, plan_file, golden_cla_ref):
    provider = _use_provider(monkeypatch, FakeProvider(response=golden_cla_ref))
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m", "--ref",
    ])
    assert rc == cli.EXIT_OK
    # En entrée : Ref + Path ; la sortie Ref est réhydratée en chemins.
    assert "Ref;Path;CurrentTitle;Date" in provider.calls[-1][1]
    df = _read_out_csv(out)
    items = df[df["Content.DescriptionLevel"] == "Item"]
    assert "inscriptions/liste_eleves_2022.xlsx" in set(items["File"])


def test_classement_batch_size_splits_calls(monkeypatch, tmp_path, input_csv,
                                            plan_file, golden_cla_path):
    df_rows = extract_csv_from_response(golden_cla_path)
    responses = [
        _batch_response(df_rows.iloc[0:2]),
        _batch_response(df_rows.iloc[2:4]),
        _batch_response(df_rows.iloc[4:6]),
    ]
    provider = _use_provider(monkeypatch, SequenceProvider(responses))
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m", "--batch-size", "2",
    ])
    assert rc == cli.EXIT_OK
    assert len(provider.calls) == 3  # un appel LLM par lot
    # Chaque lot ne contient que sa tranche d'items.
    assert "liste_eleves_2022" in provider.calls[0][1]
    assert "menus_janvier" in provider.calls[1][1]
    assert "photo_kermesse" in provider.calls[2][1]
    df = _read_out_csv(out)
    assert (df["Content.DescriptionLevel"] == "Item").sum() == 6


# ── classement --corrections (apprentissage des corrections) ──────────────────

@pytest.fixture
def corrections_file(tmp_path):
    path = tmp_path / "corrections.csv"
    path.write_text(
        "Path;TargetFolder;NewTitle\n"
        "inscriptions/liste_eleves_2022.xlsx;1-1_Inscriptions;2022_liste.xlsx\n",
        encoding="utf-8",
    )
    return path


def test_classement_corrections_injects_fewshot(monkeypatch, tmp_path, input_csv,
                                                plan_file, corrections_file, golden_cla_path):
    provider = _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m", "--corrections", str(corrections_file),
    ])
    assert rc == cli.EXIT_OK
    system_prompt, user_msg = provider.calls[-1]
    # Le canal d'exemples est ouvert côté système ET le bloc figure dans le user.
    assert "# Exemples de classements validés" in system_prompt
    assert "appliquez la même logique" in user_msg
    assert "`inscriptions/liste_eleves_2022.xlsx`" in user_msg
    # Le bloc précède la frontière de cache (préfixe stable).
    from prompts import CLA_001
    assert user_msg.index("appliquez la même logique") < user_msg.index(CLA_001.CACHE_BOUNDARY)


# ── --plan accepte un CSV Resip « dossiers seuls » ───────────────────────────

_FOLDERS_PLAN_CSV = (
    "ID;ParentID;File;Content.DescriptionLevel;Content.Title;Content.StartDate;Content.EndDate\n"
    "1;;.;RecordGrp;Fonds scolaire;;\n"
    "2;1;Fonds/Inscriptions;RecordGrp;Inscriptions;;\n"
    "3;1;Fonds/Cantine;RecordGrp;Restauration;;\n"
)


def test_classement_accepts_csv_folders_plan(monkeypatch, tmp_path, input_csv,
                                              golden_cla_path):
    """Un CSV « dossiers seuls » est converti en bloc arborescence canonique
    et le classement l'accepte comme plan validé (parité avec le wizard)."""
    plan_csv = tmp_path / "plan.csv"
    plan_csv.write_text(_FOLDERS_PLAN_CSV, encoding="utf-8")
    provider = _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_csv),
        "--out", str(out), "--model", "m",
    ])
    assert rc == cli.EXIT_OK
    # Le plan transmis au modèle porte les dossiers du CSV, renumérotés.
    user_msg = provider.calls[-1][1]
    assert "1_Inscriptions/" in user_msg and "2_Cantine/" in user_msg


def test_classement_journal_marks_plan_fourni(monkeypatch, tmp_path, input_csv,
                                              plan_file, golden_cla_path):
    """Le journal d'un `classement` consigne l'origine « plan fourni »."""
    _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    journal = tmp_path / "journal.md"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(tmp_path / "final.csv"), "--model", "m",
        "--journal", str(journal),
    ])
    assert rc == cli.EXIT_OK
    assert "fourni par l'archiviste" in journal.read_text(encoding="utf-8")


def test_classement_without_corrections_prompt_unchanged(monkeypatch, tmp_path,
                                                        input_csv, plan_file, golden_cla_path):
    provider = _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m",
    ])
    assert rc == cli.EXIT_OK
    system_prompt, user_msg = provider.calls[-1]
    # Sans --corrections : aucun bloc d'exemples (comportement 1.0.0 inchangé).
    assert "# Exemples de classements validés" not in system_prompt
    assert "appliquez la même logique" not in user_msg


def test_classement_corrections_missing_file_exits_2(monkeypatch, tmp_path,
                                                    input_csv, plan_file):
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(tmp_path / "out.csv"), "--model", "m",
        "--corrections", str(tmp_path / "absent.csv"),
    ])
    assert rc == cli.EXIT_INPUT_INVALID


# ── consignes de classement --directives ─────────────────────────────────────

def _directives_file(tmp_path):
    f = tmp_path / "consignes.txt"
    f.write_text(
        "2_Cantine: un sous-dossier par prestataire [+sous-dossiers]\n"
        "Nommer les fichiers en français\n",
        encoding="utf-8",
    )
    return f


def test_classement_directives_inject_channel(monkeypatch, tmp_path, input_csv,
                                              plan_file, golden_cla_path):
    provider = _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(tmp_path / "final.csv"), "--model", "m",
        "--directives", str(_directives_file(tmp_path)),
    ])
    assert rc == cli.EXIT_OK
    system_prompt, user_msg = provider.calls[-1]
    assert "# Consignes de classement de l'archiviste" in system_prompt
    assert "un sous-dossier par prestataire" in user_msg
    # Le bloc précède la frontière de cache (préfixe stable).
    from prompts import CLA_001
    assert user_msg.index("un sous-dossier par prestataire") < user_msg.index(CLA_001.CACHE_BOUNDARY)


def test_classement_directives_create_subfolder_end_to_end(monkeypatch, tmp_path,
                                                          input_csv, plan_file):
    """Le modèle range les items de cantine dans un sous-dossier `2_Cantine/…` ;
    avec la consigne autorisant la création, le CSV RESIP produit contient le
    sous-dossier créé, rattaché à 2_Cantine."""
    # Réponse LLM ciblant un sous-dossier à créer sous 2_Cantine.
    cla = (
        "```csv\n"
        "Path;TargetFolder;NewTitle\n"
        "cantine/menus_janvier.docx;2_Cantine/Prestataire A;2022-01-03_menus.docx\n"
        "cantine/facture_traiteur_2021.pdf;2_Cantine/Prestataire A;2021-11-15_facture.pdf\n"
        "```\n"
    )
    _use_provider(monkeypatch, FakeProvider(response=cla))
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m",
        "--directives", str(_directives_file(tmp_path)),
    ])
    assert rc == cli.EXIT_OK
    import pandas as pd
    df = pd.read_csv(out, sep=";", dtype=str)
    folders = set(df[df["Content.DescriptionLevel"] == "RecordGrp"]["File"])
    assert "2-3_Prestataire_A" in folders  # 2-1/2-2 pris → 2-3
    rg = df[df["Content.DescriptionLevel"] == "RecordGrp"].set_index("File")
    assert rg.loc["2-3_Prestataire_A", "ParentID"] == rg.loc["2_Cantine", "ID"]


def test_classement_without_directives_prompt_unchanged(monkeypatch, tmp_path,
                                                       input_csv, plan_file, golden_cla_path):
    provider = _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(tmp_path / "final.csv"), "--model", "m",
    ])
    assert rc == cli.EXIT_OK
    system_prompt, _ = provider.calls[-1]
    assert "# Consignes de classement de l'archiviste" not in system_prompt


def test_classement_directives_missing_file_exits_2(tmp_path, input_csv, plan_file):
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(tmp_path / "out.csv"), "--model", "m",
        "--directives", str(tmp_path / "absent.txt"),
    ])
    assert rc == cli.EXIT_INPUT_INVALID


def test_classement_corrections_dry_run_shows_examples(tmp_path, input_csv,
                                                     plan_file, corrections_file, capsys):
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--corrections", str(corrections_file), "--dry-run", "--json",
    ])
    assert rc == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    cla = payload["agents"][0]
    from prompts import CLA_001
    assert cla["promptVersion"] == CLA_001.PROMPT_VERSION
    assert "appliquez la même logique" in cla["prompts"]["user"]
    assert "# Exemples de classements validés" in cla["prompts"]["system"]


# ── classement --concurrency (lots en parallèle) ──────────────────────────────

class _RoutedProvider(FakeProvider):
    """Provider mocké **sûr en parallèle** : choisit sa réponse selon un marqueur
    distinctif présent dans le user_message (sans état d'ordre). Une instance
    fraîche par appel à `get_provider` (comme en production)."""

    def __init__(self, routes):
        super().__init__()
        self.routes = routes

    def stream_with_reasoning(self, system_prompt, user_message, *, cache_user_boundary=None):
        for marker, resp in self.routes:
            if marker in user_message:
                self.response = resp
                break
        yield from FakeProvider.stream_with_reasoning(
            self, system_prompt, user_message, cache_user_boundary=cache_user_boundary
        )


def _routes_from_golden(golden_cla_path):
    df_rows = extract_csv_from_response(golden_cla_path)
    markers = ["liste_eleves_2022", "menus_janvier", "photo_kermesse"]
    slices = [df_rows.iloc[0:2], df_rows.iloc[2:4], df_rows.iloc[4:6]]
    return [(markers[k], _batch_response(slices[k])) for k in range(3)]


def test_classement_concurrency_parallel_produces_resip(monkeypatch, tmp_path,
                                                        input_csv, plan_file, golden_cla_path):
    """`--concurrency 3` traite les lots en parallèle (cloud) : un provider isolé
    par lot, résultat RESIP identique au séquentiel (6 items)."""
    routes = _routes_from_golden(golden_cla_path)
    created = []

    def factory(**kw):
        p = _RoutedProvider(routes)
        created.append(p)
        return p

    monkeypatch.setattr(cli, "get_provider", factory)
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "gpt-5.1", "--batch-size", "2",
        "--concurrency", "3",
    ])
    assert rc == cli.EXIT_OK
    # Un provider qui a effectivement streamé par lot (isolation thread) —
    # plus le provider de validation de config (sans appel).
    streamed = [p for p in created if p.calls]
    assert len(streamed) == 3
    assert all(len(p.calls) == 1 for p in streamed)
    df = _read_out_csv(out)
    assert (df["Content.DescriptionLevel"] == "Item").sum() == 6


def test_classement_concurrency_local_forced_sequential(monkeypatch, tmp_path, capsys,
                                                        input_csv, plan_file, golden_cla_path):
    """Serveur local (`--base-url`) : `--concurrency` est ignoré (mono-requête) —
    traitement séquentiel, avertissement émis."""
    df_rows = extract_csv_from_response(golden_cla_path)
    responses = [
        _batch_response(df_rows.iloc[0:2]),
        _batch_response(df_rows.iloc[2:4]),
        _batch_response(df_rows.iloc[4:6]),
    ]
    provider = _use_provider(monkeypatch, SequenceProvider(responses))
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "qwen3:14b",
        "--base-url", "http://localhost:1234/v1",
        "--batch-size", "2", "--concurrency", "3",
    ])
    assert rc == cli.EXIT_OK
    assert len(provider.calls) == 3  # séquentiel : un seul provider partagé
    err = capsys.readouterr().err
    assert "concurrency" in err and "séquentiel" in err.lower()


def test_classement_concurrency_resume_skips_llm(monkeypatch, tmp_path,
                                                 input_csv, plan_file, golden_cla_path):
    """En parallèle, les lots déjà sur disque (`--resume`) ne rappellent pas le LLM."""
    routes = _routes_from_golden(golden_cla_path)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    # Pré-écrit le lot 1 comme s'il avait déjà été produit.
    (raw_dir / "cla_lot_001.txt").write_text(routes[0][1], encoding="utf-8")
    created = []

    def factory(**kw):
        p = _RoutedProvider(routes)
        created.append(p)
        return p

    monkeypatch.setattr(cli, "get_provider", factory)
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "gpt-5.1", "--batch-size", "2",
        "--concurrency", "3", "--raw-dir", str(raw_dir), "--resume",
    ])
    assert rc == cli.EXIT_OK
    # Seuls les lots 2 et 3 appellent le LLM (le lot 1 est repris du disque).
    streamed = [p for p in created if p.calls]
    assert len(streamed) == 2
    df = _read_out_csv(out)
    assert (df["Content.DescriptionLevel"] == "Item").sum() == 6


@pytest.mark.parametrize("requested,model,base_url,expected", [
    (None, "gpt-5.1", None, 1),       # défaut = séquentiel
    (1, "gpt-5.1", None, 1),
    (3, "gpt-5.1", None, 3),          # cloud : respecté
    (9, "gpt-5.1", None, 4),          # borné au maximum
    (3, "qwen3:14b", "http://x", 1),  # serveur local : forcé séquentiel
    (3, "ollama/qwen3:14b", None, 1),  # préfixe local : forcé séquentiel
])
def test_resolve_concurrency(requested, model, base_url, expected):
    args = argparse.Namespace(concurrency=requested, model=model, base_url=base_url)
    assert cli._resolve_concurrency(args) == expected


def test_classement_unusable_output_exits_3(monkeypatch, tmp_path, input_csv, plan_file):
    """Réponse sans CSV exploitable : la conversion échoue → EXIT_OUTPUT_INVALID."""
    _use_provider(monkeypatch, FakeProvider(response="Je refuse de classer."))
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(tmp_path / "final.csv"), "--model", "m",
    ])
    assert rc == cli.EXIT_OUTPUT_INVALID


def test_classement_missing_plan_exits_2(monkeypatch, tmp_path, input_csv):
    # Le plan est chargé par `_load_plan_file` (unifié avec `_load_input_csv`) :
    # un fichier absent quitte via SystemExit(EXIT_INPUT_INVALID), comme l'audit.
    _use_provider(monkeypatch, FakeProvider())
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "classement", str(input_csv), "--plan", str(tmp_path / "absent.md"),
            "--out", str(tmp_path / "f.csv"), "--model", "m",
        ])
    assert exc.value.code == cli.EXIT_INPUT_INVALID


# ── classement --interactive ─────────────────────────────────────────────────

def test_classement_interactive_confirm_writes(monkeypatch, tmp_path, input_csv,
                                               plan_file, golden_cla_path, capsys):
    """Confirmation acceptée : le CSV est écrit, l'aperçu de conformité est
    affiché AVANT l'écriture (sur stderr)."""
    _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    monkeypatch.setattr("builtins.input", lambda: "o")
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m", "--interactive",
    ])
    assert rc == cli.EXIT_OK
    assert out.is_file()
    err = capsys.readouterr().err
    # L'aperçu (« Respect du plan ») précède le message d'écriture.
    assert "Respect du plan" in err
    assert err.index("Respect du plan") < err.index("CSV RESIP écrit")


def test_classement_interactive_decline_writes_nothing(monkeypatch, tmp_path,
                                                       input_csv, plan_file,
                                                       golden_cla_path):
    """Refus (réponse vide) : aucun fichier produit, EXIT_OK, written=False."""
    _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    monkeypatch.setattr("builtins.input", lambda: "")
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m", "--interactive",
    ])
    assert rc == cli.EXIT_OK
    assert not out.exists()


def test_classement_interactive_decline_json_written_false(monkeypatch, tmp_path,
                                                          input_csv, plan_file,
                                                          golden_cla_path, capsys):
    """Refus + --json : le résumé porte written=false et paths vide, sans CSV."""
    _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    monkeypatch.setattr("builtins.input", lambda: "non")
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m", "--interactive", "--json",
    ])
    assert rc == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["written"] is False
    assert payload["paths"] == {}
    assert not out.exists()
    # Les stats de conformité restent exposées (l'aperçu a bien eu lieu).
    assert "planMatches" in payload["stats"]


def test_classement_interactive_eof_declines(monkeypatch, tmp_path, input_csv,
                                             plan_file, golden_cla_path):
    """stdin fermé (EOF, ex. non-TTY) : refus par défaut, rien n'est écrit."""
    _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    def _raise_eof():
        raise EOFError
    monkeypatch.setattr("builtins.input", _raise_eof)
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m", "-i",
    ])
    assert rc == cli.EXIT_OK
    assert not out.exists()


# ── run (pipeline complet) + artefacts/reprise ───────────────────────────────

def test_run_full_pipeline_artifacts(monkeypatch, tmp_path, input_csv,
                                     golden_aud, golden_cla_path):
    provider = _use_provider(monkeypatch, SequenceProvider([golden_aud, golden_cla_path]))
    out_dir = tmp_path / "out"
    rc = cli.main(["run", str(input_csv), "--out-dir", str(out_dir), "--model", "m"])
    assert rc == cli.EXIT_OK
    assert len(provider.calls) == 2  # audit + classement
    assert (out_dir / "rapport.md").is_file()
    assert (out_dir / "plan.md").is_file()
    assert (out_dir / "notes.md").is_file()
    finals = list(out_dir.glob("classement_final_*.csv"))
    assert len(finals) == 1
    # Artefact brut du classement : base de la reprise.
    assert (out_dir / "raw" / "cla_complet.txt").read_text(encoding="utf-8") == golden_cla_path


def test_run_writes_manifest(monkeypatch, tmp_path, input_csv,
                             golden_aud, golden_cla_path):
    """`run` écrit un manifest.json self-contained : issue, modèle, versions
    de prompt, durée, et l'inventaire (chemins relatifs) de tous les artefacts,
    réponses LLM brutes incluses (rapport.md + raw/*.txt)."""
    _use_provider(monkeypatch, SequenceProvider([golden_aud, golden_cla_path]))
    out_dir = tmp_path / "out"
    rc = cli.main(["run", str(input_csv), "--out-dir", str(out_dir), "--model", "m"])
    assert rc == cli.EXIT_OK

    manifest_path = out_dir / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["command"] == "run"
    assert manifest["ok"] is True
    assert manifest["exitCode"] == cli.EXIT_OK
    assert manifest["model"] == "m"
    assert manifest["resumed"] is False
    assert manifest["startedAt"] and manifest["finishedAt"]
    assert manifest["promptVersions"]["AUD-001"]
    assert manifest["promptVersions"]["CLA-001"]
    assert manifest["audit"]["command"] == "audit"
    assert manifest["classement"]["command"] == "classement"

    # Inventaire des artefacts : chemins relatifs (portable), réponses brutes
    # incluses, tous les fichiers listés existent réellement.
    by_role = {a["role"]: a["path"] for a in manifest["artifacts"]}
    assert by_role["audit_raw"] == "rapport.md"
    assert by_role["plan"] == "plan.md"
    assert by_role["notes"] == "notes.md"
    assert by_role["classement_raw"] == "raw/cla_complet.txt"
    assert by_role["classement_csv"].startswith("classement_final_")
    for art in manifest["artifacts"]:
        assert not Path(art["path"]).is_absolute()
        assert (out_dir / art["path"]).is_file()


def test_run_manifest_written_on_partial_failure(monkeypatch, tmp_path, input_csv):
    """Plan d'audit non extrait : le manifeste est tout de même écrit, ok=false,
    et n'inventorie que les artefacts d'audit présents (pas de CSV de classement)."""
    _use_provider(monkeypatch, FakeProvider(response="Réponse sans plan."))
    out_dir = tmp_path / "out"
    rc = cli.main(["run", str(input_csv), "--out-dir", str(out_dir), "--model", "m"])
    assert rc == cli.EXIT_OUTPUT_INVALID

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ok"] is False
    assert manifest["exitCode"] == cli.EXIT_OUTPUT_INVALID
    roles = {a["role"] for a in manifest["artifacts"]}
    assert "audit_raw" in roles
    assert "classement_csv" not in roles
    assert "classement_raw" not in roles


# ── Journal de traitement ─────────────────────────────────────────────────────

def test_run_journal_written(monkeypatch, tmp_path, input_csv,
                             golden_aud, golden_cla_path):
    """`run --journal FICHIER` écrit un journal de traçabilité Markdown :
    fichier traité, modèle, versions de prompt, durée, confidentialité."""
    _use_provider(monkeypatch, SequenceProvider([golden_aud, golden_cla_path]))
    out_dir = tmp_path / "out"
    journal_path = tmp_path / "journal.md"
    rc = cli.main([
        "run", str(input_csv), "--out-dir", str(out_dir), "--model", "m",
        "--journal", str(journal_path),
    ])
    assert rc == cli.EXIT_OK
    assert journal_path.is_file()
    md = journal_path.read_text(encoding="utf-8")
    assert md.startswith("# Journal de traitement ODACEA")
    assert "vrac.csv" in md
    assert "Modèle : m" in md
    assert "AUD-001 v" in md and "CLA-001 v" in md
    assert "## Confidentialité des données" in md
    assert "métadonnées" in md


def test_run_journal_in_json_payload(monkeypatch, tmp_path, input_csv, capsys,
                                     golden_aud, golden_cla_path):
    """Avec --json, le résumé `run` imbrique l'objet `journal`."""
    _use_provider(monkeypatch, SequenceProvider([golden_aud, golden_cla_path]))
    out_dir = tmp_path / "out"
    rc = cli.main([
        "run", str(input_csv), "--out-dir", str(out_dir), "--model", "m",
        "--journal", str(tmp_path / "journal.md"), "--json",
    ])
    assert rc == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    journal = payload["journal"]
    assert journal["tool"] == "ODACEA"
    assert journal["command"] == "run"
    assert journal["source"]["file"] == "vrac.csv"
    assert journal["outcome"] == {"ok": True, "exitCode": cli.EXIT_OK}
    assert journal["promptVersions"]["AUD-001"]
    assert journal["confidentiality"]


def test_no_journal_without_flag(monkeypatch, tmp_path, input_csv, capsys,
                                 golden_aud, golden_cla_path):
    """Opt-in : sans --journal, aucun journal n'est écrit ni joint au --json."""
    _use_provider(monkeypatch, SequenceProvider([golden_aud, golden_cla_path]))
    out_dir = tmp_path / "out"
    rc = cli.main([
        "run", str(input_csv), "--out-dir", str(out_dir), "--model", "m", "--json",
    ])
    assert rc == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert "journal" not in payload
    assert not list(tmp_path.glob("*.md"))  # aucun journal Markdown créé par le run


def test_audit_journal_records_missing_plan(monkeypatch, tmp_path, input_csv):
    """Un audit sans plan extrait consigne l'anomalie et ok reste mesurable."""
    _use_provider(monkeypatch, FakeProvider(response="Réponse sans plan."))
    journal_path = tmp_path / "journal.md"
    rc = cli.main([
        "audit", str(input_csv), "--model", "m", "--journal", str(journal_path),
    ])
    assert rc == cli.EXIT_OK
    md = journal_path.read_text(encoding="utf-8")
    assert "Plan non extrait du rapport d'audit." in md
    assert "## Anomalies (1)" in md


def test_run_journal_on_partial_failure(monkeypatch, tmp_path, input_csv):
    """Plan non extrait : le journal est tout de même écrit, ok=false."""
    _use_provider(monkeypatch, FakeProvider(response="Réponse sans plan."))
    out_dir = tmp_path / "out"
    journal_path = tmp_path / "journal.md"
    rc = cli.main([
        "run", str(input_csv), "--out-dir", str(out_dir), "--model", "m",
        "--journal", str(journal_path),
    ])
    assert rc == cli.EXIT_OUTPUT_INVALID
    md = journal_path.read_text(encoding="utf-8")
    assert "échec" in md
    assert "classement non exécuté" in md


# ── Manifeste d'arborescence modèle ──────────────────────────────────────────

def test_classement_manifest_written(monkeypatch, tmp_path, input_csv,
                                     plan_file, golden_cla_path):
    """`classement --manifest FICHIER` écrit l'arborescence de répertoires
    cible dérivée du CSV RESIP produit (Markdown, métadonnées seules)."""
    _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    out = tmp_path / "final.csv"
    manifest_path = tmp_path / "arborescence.md"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m", "--manifest", str(manifest_path),
    ])
    assert rc == cli.EXIT_OK
    assert manifest_path.is_file()
    md = manifest_path.read_text(encoding="utf-8")
    assert md.startswith("# Arborescence de répertoires modèle ODACEA")
    assert "## Arborescence cible" in md
    assert "## Répertoires modèle" in md
    assert "métadonnées seules" in md.lower()


def test_classement_manifest_in_json_payload(monkeypatch, tmp_path, input_csv,
                                             plan_file, golden_cla_path, capsys):
    """Avec --json, le résumé `classement` imbrique l'objet `manifest`
    (et le chemin écrit dans `paths.manifest`)."""
    _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    out = tmp_path / "final.csv"
    manifest_path = tmp_path / "arborescence.md"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m",
        "--manifest", str(manifest_path), "--json",
    ])
    assert rc == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    manifest = payload["manifest"]
    assert manifest["tool"] == "ODACEA"
    assert manifest["summary"]["items"] == 6
    assert manifest["directories"]  # au moins un répertoire cible
    assert payload["paths"]["manifest"] == str(manifest_path)


def test_no_manifest_without_flag(monkeypatch, tmp_path, input_csv,
                                  plan_file, golden_cla_path, capsys):
    """Opt-in : sans --manifest, aucun manifeste écrit ni joint au --json."""
    _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    out = tmp_path / "final.csv"
    manifest_path = tmp_path / "arborescence.md"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m", "--json",
    ])
    assert rc == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert "manifest" not in payload
    assert "manifest" not in payload["paths"]
    assert not manifest_path.exists()


def test_run_manifest_written(monkeypatch, tmp_path, input_csv,
                              golden_aud, golden_cla_path):
    """`run --manifest FICHIER` écrit aussi le manifeste (pipeline complet)."""
    _use_provider(monkeypatch, SequenceProvider([golden_aud, golden_cla_path]))
    out_dir = tmp_path / "out"
    manifest_path = tmp_path / "arborescence.md"
    rc = cli.main([
        "run", str(input_csv), "--out-dir", str(out_dir), "--model", "m",
        "--manifest", str(manifest_path),
    ])
    assert rc == cli.EXIT_OK
    assert manifest_path.is_file()
    assert "Arborescence de répertoires modèle" in manifest_path.read_text(encoding="utf-8")


def test_run_resume_skips_paid_steps(monkeypatch, tmp_path, input_csv,
                                     golden_aud, golden_cla_path):
    """Run interrompu après l'audit : --resume réutilise rapport.md et ne
    rappelle le LLM que pour le classement manquant."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "rapport.md").write_text(golden_aud, encoding="utf-8")

    provider = _use_provider(monkeypatch, SequenceProvider([golden_cla_path]))
    rc = cli.main([
        "run", str(input_csv), "--out-dir", str(out_dir), "--model", "m", "--resume",
    ])
    assert rc == cli.EXIT_OK
    assert len(provider.calls) == 1  # l'audit n'a pas été repayé
    assert "TargetFolder" in provider.calls[0][0] or "TargetFolder" in provider.calls[0][1]


def test_classement_resume_skips_saved_batches(monkeypatch, tmp_path, input_csv,
                                               plan_file, golden_cla_path):
    """Lots 1 et 2 déjà sur disque : --resume ne rappelle que le lot 3."""
    df_rows = extract_csv_from_response(golden_cla_path)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "cla_lot_001.txt").write_text(_batch_response(df_rows.iloc[0:2]), encoding="utf-8")
    (raw_dir / "cla_lot_002.txt").write_text(_batch_response(df_rows.iloc[2:4]), encoding="utf-8")

    provider = _use_provider(
        monkeypatch, SequenceProvider([_batch_response(df_rows.iloc[4:6])])
    )
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m", "--batch-size", "2",
        "--raw-dir", str(raw_dir), "--resume",
    ])
    assert rc == cli.EXIT_OK
    assert len(provider.calls) == 1  # seuls les lots manquants sont payés
    assert (raw_dir / "cla_lot_003.txt").is_file()  # et sauvegardés à leur tour
    df = _read_out_csv(out)
    assert (df["Content.DescriptionLevel"] == "Item").sum() == 6


def test_classement_full_resume_needs_no_model(monkeypatch, tmp_path, input_csv,
                                               plan_file, golden_cla_path):
    """Tous les lots sur disque : aucune config LLM requise (provider jamais construit)."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "cla_complet.txt").write_text(golden_cla_path, encoding="utf-8")
    monkeypatch.setattr(cli, "DEFAULT_MODEL", "")
    monkeypatch.setattr(cli, "get_provider",
                        lambda **kw: pytest.fail("le LLM ne doit pas être appelé"))
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(tmp_path / "final.csv"),
        "--raw-dir", str(raw_dir), "--resume",
    ])
    assert rc == cli.EXIT_OK


# ── eval (harnais d'évaluation des prompts —) ────────────────────────────────

def test_eval_both_writes_report_and_table(monkeypatch, tmp_path, capsys, input_csv,
                                           golden_aud, golden_cla_path):
    """`cli.py eval` produit un rapport JSON historisé + tableau lisible."""
    import json

    from prompts import AGT_001, AUD_001, CLA_001

    _use_provider(monkeypatch, SequenceProvider([golden_aud, golden_cla_path]))
    results_dir = tmp_path / "results"
    rc = cli.main([
        "eval", "--input", str(input_csv), "--model", "m",
        "--results-dir", str(results_dir),
    ])
    assert rc == cli.EXIT_OK

    # Rapport JSON historisé, versions de prompt consignées.
    files = list(results_dir.glob("*.json"))
    assert len(files) == 1
    report = json.loads(files[0].read_text(encoding="utf-8"))
    assert report["promptVersions"] == {
        "AUD-001": AUD_001.PROMPT_VERSION,
        "CLA-001": CLA_001.PROMPT_VERSION,
        "AGT-001": AGT_001.PROMPT_VERSION,
    }
    assert [r["agent"] for r in report["runs"]] == ["AUD-001", "CLA-001"]
    aud, cla = report["runs"]
    assert aud["metrics"]["planExtracted"] is True
    assert aud["usage"]["total_tokens"] == 1200
    assert cla["mode"] == "path"
    assert cla["metrics"]["itemsClassified"] == 6
    assert cla["metrics"]["planMatches"] is True

    # Tableau lisible sur stdout (les logs vont sur stderr).
    out = capsys.readouterr().out
    assert "AUD-001 — audit" in out
    assert "CLA-001 — classement" in out
    assert f"AUD-001 v{AUD_001.PROMPT_VERSION}" in out


def test_eval_cla_mode_both_objectifies_path_vs_ref(monkeypatch, tmp_path, capsys,
                                                    input_csv, plan_file,
                                                    golden_cla_path, golden_cla_ref):
    """La matrice croise les deux méthodes d'identifiant sur le même jeu."""
    provider = _use_provider(
        monkeypatch, SequenceProvider([golden_cla_path, golden_cla_ref])
    )
    rc = cli.main([
        "eval", "--input", str(input_csv), "--model", "m",
        "--agent", "cla", "--plan", str(plan_file), "--cla-mode", "both",
        "--no-save",
    ])
    assert rc == cli.EXIT_OK
    assert len(provider.calls) == 2
    # 1er appel : mode Path (identifiant = chemin) ; 2e : mode Ref.
    assert "Path;CurrentTitle;Date" in provider.calls[0][1]
    assert "Ref;Path;CurrentTitle;Date" in provider.calls[1][1]
    out = capsys.readouterr().out
    assert "path" in out and "ref" in out


def test_eval_cla_alone_requires_plan(monkeypatch, input_csv):
    _use_provider(monkeypatch, FakeProvider())
    rc = cli.main(["eval", "--input", str(input_csv), "--model", "m",
                   "--agent", "cla", "--no-save"])
    assert rc == cli.EXIT_CONFIG_ERROR


def test_eval_llm_error_recorded_not_fatal(monkeypatch, tmp_path, capsys, input_csv,
                                           golden_aud):
    """Un modèle injoignable n'interrompt pas la matrice : le run est consigné
    en erreur ; le code de sortie n'est non-nul que si TOUT a échoué."""
    provider = FakeProvider(response=golden_aud)
    provider.failures = [RuntimeError("connexion refusée")]
    _use_provider(monkeypatch, provider)
    rc = cli.main([
        "eval", "--input", str(input_csv), "--model", "m-a", "--model", "m-b",
        "--agent", "aud", "--no-save",
    ])
    assert rc == cli.EXIT_OK  # le second modèle a réussi
    out = capsys.readouterr().out
    assert "ERREUR : connexion refusée" in out


def test_eval_all_failed_exits_1(monkeypatch, input_csv):
    provider = FakeProvider()
    provider.failures = [RuntimeError("down")]
    _use_provider(monkeypatch, provider)
    rc = cli.main(["eval", "--input", str(input_csv), "--model", "m",
                   "--agent", "aud", "--no-save"])
    assert rc == cli.EXIT_LLM_ERROR


# ── eval --agent agt (agent, golden files de requêtes) ───────────────────────

def _agt_cases_file(tmp_path):
    cases = {"cases": [
        {"id": "pdf", "question": "Combien de PDF ?", "attendu": {
            "type": "requete", "outils": ["compter"],
            "filtre": {"extension": "pdf"}, "verifierTotal": True}},
        {"id": "xlsx", "question": "Montre-moi des fichiers xlsx.", "attendu": {
            "type": "requete", "outils": ["echantillonner"],
            "filtre": {"extension": "xlsx"}}},
    ]}
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    return path


def test_eval_agt_golden_cases(monkeypatch, tmp_path, capsys, input_csv):
    """`eval --agent agt --cases` mesure l'exactitude des tool-calls et
    des filtres émis contre le corpus golden (rapport JSON + tableau AGT-001).
    Chaque cas tourne sur une session fraîche ; le total exact de la réponse
    est vérifié contre Pandas, jamais contre un chiffre écrit en dur."""
    from prompts import AGT_001
    from tests.conftest import FakeToolProvider

    provider = FakeToolProvider([
        [("compter", '{"filtre": {"extension": "pdf"}}')],
        "Il y a 1 fichier PDF dans ce vrac.",
        [("echantillonner", '{"filtre": {"extension": "xlsx"}}')],
        "Voici quelques fichiers xlsx.",
    ])
    _use_provider(monkeypatch, provider)
    results_dir = tmp_path / "results"
    rc = cli.main([
        "eval", "--agent", "agt", "--input", str(input_csv),
        "--cases", str(_agt_cases_file(tmp_path)), "--model", "claude-test",
        "--results-dir", str(results_dir),
    ])
    assert rc == cli.EXIT_OK

    report = json.loads(next(results_dir.glob("*.json")).read_text(encoding="utf-8"))
    (run,) = report["runs"]
    assert run["agent"] == "AGT-001"
    assert run["mode"] == "native"  # claude-* sans base_url → function calling natif
    assert run["metrics"]["reussis"] == 2
    assert run["metrics"]["exactitudePct"] == 100.0
    assert [c["reussi"] for c in run["cases"]] == [True, True]
    assert report["promptVersions"]["AGT-001"] == AGT_001.PROMPT_VERSION
    assert report["options"]["cases"].endswith("cases.json")

    out = capsys.readouterr().out
    assert "AGT-001 — agent" in out
    assert f"AGT-001 v{AGT_001.PROMPT_VERSION}" in out


def test_eval_agt_cas_en_echec_n_interrompt_pas(monkeypatch, tmp_path, input_csv):
    """Matrice tolérante (même politique que CLA-001) : un cas en erreur LLM
    est consigné, les cas suivants tournent, l'exactitude le compte en échec."""
    from tests.conftest import FakeToolProvider

    class FailingFirst(FakeToolProvider):
        def complete_with_tools(self, messages, tools=None):
            if not self.calls:
                self.calls.append({"messages": messages, "tools": tools})
                raise RuntimeError("connexion refusée")
            return super().complete_with_tools(messages, tools)

    provider = FailingFirst([
        [("echantillonner", '{"filtre": {"extension": "xlsx"}}')],
        "Voici quelques fichiers xlsx.",
    ])
    _use_provider(monkeypatch, provider)
    rc = cli.main([
        "eval", "--agent", "agt", "--input", str(input_csv),
        "--cases", str(_agt_cases_file(tmp_path)), "--model", "claude-test",
        "--no-save", "--json",
    ])
    assert rc == cli.EXIT_OK


def test_eval_agt_exige_cases(monkeypatch, input_csv):
    _use_provider(monkeypatch, FakeProvider())
    rc = cli.main(["eval", "--agent", "agt", "--input", str(input_csv),
                   "--model", "m", "--no-save"])
    assert rc == cli.EXIT_CONFIG_ERROR


def test_eval_cases_sans_agt_refuse(monkeypatch, tmp_path, input_csv):
    _use_provider(monkeypatch, FakeProvider())
    rc = cli.main(["eval", "--input", str(input_csv), "--model", "m",
                   "--cases", str(_agt_cases_file(tmp_path)), "--no-save"])
    assert rc == cli.EXIT_CONFIG_ERROR


def test_eval_agt_corpus_invalide(monkeypatch, tmp_path, input_csv):
    _use_provider(monkeypatch, FakeProvider())
    bad = tmp_path / "bad.json"
    bad.write_text('{"cases": [{"question": ""}]}', encoding="utf-8")
    rc = cli.main(["eval", "--agent", "agt", "--input", str(input_csv),
                   "--cases", str(bad), "--model", "m", "--no-save"])
    assert rc == cli.EXIT_INPUT_INVALID


# ── Sortie machine --json ────────────────────────────────────────────────────

def _stdout_json(capsys):
    """stdout ne porte qu'un seul document JSON ; les logs sont sur stderr."""
    import json

    captured = capsys.readouterr()
    return json.loads(captured.out), captured.err


# ── enrich --fingerprint ─────────────────────────────────────────────────────

def _fp_csv_and_root(tmp_path):
    """CSV minimal + arborescence locale : deux fichiers binairement identiques."""
    root = tmp_path / "src"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir(parents=True)
    (root / "a" / "doc.pdf").write_bytes(b"meme contenu")
    (root / "b" / "doc.pdf").write_bytes(b"meme contenu")   # doublon strict
    (root / "a" / "autre.pdf").write_bytes(b"contenu distinct")
    csv = tmp_path / "vrac.csv"
    csv.write_text(
        "ID;ParentID;File;Content.DescriptionLevel;Content.Title;"
        "Content.StartDate;Content.EndDate\n"
        "1;;.;RecordGrp;racine;;\n"
        "2;1;a/doc.pdf;Item;doc.pdf;;\n"
        "3;1;b/doc.pdf;Item;doc.pdf;;\n"
        "4;1;a/autre.pdf;Item;autre.pdf;;\n",
        encoding="utf-8",
    )
    return csv, root


def test_enrich_fingerprint_only_reports_strict_duplicates(tmp_path, capsys):
    csv, root = _fp_csv_and_root(tmp_path)
    out = tmp_path / "out.csv"
    rc = cli.main([
        "enrich", str(csv), "--source-root", str(root),
        "--fingerprint-only", "--output", str(out), "--json",
    ])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    # Fingerprint-only : pas d'extraction de description, mais des empreintes.
    assert "report" not in payload
    assert payload["fingerprint"]["hashed"] == 3
    assert payload["duplicates"]["groups"] == 1
    assert payload["duplicates"]["redundant"] == 1
    # Le CSV de sortie porte la colonne d'empreinte, identique sur les doublons.
    from core.enrich import FINGERPRINT_COLUMN
    df = _read_out_csv(out)
    assert FINGERPRINT_COLUMN in df.columns
    fps = df[df["Content.DescriptionLevel"] == "Item"][FINGERPRINT_COLUMN].tolist()
    assert fps[0] == fps[1] and fps[0] != fps[2]


def test_enrich_without_fingerprint_omits_section(tmp_path, capsys):
    csv, root = _fp_csv_and_root(tmp_path)
    out = tmp_path / "out.csv"
    rc = cli.main([
        "enrich", str(csv), "--source-root", str(root),
        "--output", str(out), "--json",
    ])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    # Sans --fingerprint : enrichissement de description seul, aucune empreinte.
    assert "report" in payload
    assert "fingerprint" not in payload
    from core.enrich import FINGERPRINT_COLUMN
    assert FINGERPRINT_COLUMN not in _read_out_csv(out).columns


def test_audit_json_emits_summary_on_stdout(monkeypatch, tmp_path, capsys,
                                            input_csv, golden_aud):
    _use_provider(monkeypatch, FakeProvider(response=golden_aud))
    rc = cli.main([
        "audit", str(input_csv),
        "--out-report", str(tmp_path / "rapport.md"),
        "--out-plan", str(tmp_path / "plan.md"),
        "--model", "test-model", "--json",
    ])
    assert rc == cli.EXIT_OK
    payload, err = _stdout_json(capsys)
    assert payload["command"] == "audit"
    assert payload["ok"] is True and payload["exitCode"] == cli.EXIT_OK
    assert payload["model"] == "test-model"
    assert payload["planExtracted"] is True
    assert payload["usage"]["total_tokens"] == 1200
    assert payload["paths"]["report"].endswith("rapport.md")
    assert payload["paths"]["notes"] is None  # --out-notes non passé
    # Les logs humains restent sur stderr — stdout est du JSON pur.
    assert "✓ CSV chargé" in err


def test_classement_json_emits_stats(monkeypatch, tmp_path, capsys, input_csv,
                                     plan_file, golden_cla_path):
    _use_provider(monkeypatch, FakeProvider(response=golden_cla_path))
    out = tmp_path / "final.csv"
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(out), "--model", "m", "--json",
    ])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    assert payload["command"] == "classement"
    assert payload["ok"] is True
    assert payload["items"] == 6
    assert "planMatches" in payload["stats"]
    assert payload["stats"]["planMatches"] is True
    assert payload["paths"]["out"].endswith("final.csv")
    assert payload["usage"]["total_tokens"] == 1200


def test_classement_json_error_envelope(monkeypatch, tmp_path, capsys, input_csv,
                                        plan_file):
    """Réponse inexploitable : EXIT_OUTPUT_INVALID + enveloppe JSON ok=false."""
    _use_provider(monkeypatch, FakeProvider(response="Je refuse de classer."))
    rc = cli.main([
        "classement", str(input_csv), "--plan", str(plan_file),
        "--out", str(tmp_path / "final.csv"), "--model", "m", "--json",
    ])
    assert rc == cli.EXIT_OUTPUT_INVALID
    payload, _ = _stdout_json(capsys)
    assert payload["command"] == "classement"
    assert payload["ok"] is False
    assert payload["exitCode"] == cli.EXIT_OUTPUT_INVALID


def test_run_json_combines_audit_and_classement(monkeypatch, tmp_path, capsys,
                                                input_csv, golden_aud, golden_cla_path):
    _use_provider(monkeypatch, SequenceProvider([golden_aud, golden_cla_path]))
    out_dir = tmp_path / "out"
    rc = cli.main(["run", str(input_csv), "--out-dir", str(out_dir),
                   "--model", "m", "--json"])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    assert payload["command"] == "run"
    assert payload["ok"] is True
    assert payload["audit"]["planExtracted"] is True
    assert payload["classement"]["items"] == 6
    assert payload["durationS"] is not None


def test_json_error_envelope_on_deep_exit(monkeypatch, tmp_path, capsys):
    """CSV introuvable : sys.exit profond — une enveloppe JSON est tout de même
    émise sur stdout avant la propagation du code (scriptabilité)."""
    _use_provider(monkeypatch, FakeProvider())
    with pytest.raises(SystemExit) as exc:
        cli.main(["audit", str(tmp_path / "absent.csv"), "--model", "m", "--json"])
    assert exc.value.code == cli.EXIT_INPUT_INVALID
    payload, _ = _stdout_json(capsys)
    assert payload["command"] == "audit"
    assert payload["ok"] is False
    assert payload["exitCode"] == cli.EXIT_INPUT_INVALID


def test_eval_json_emits_report_not_table(monkeypatch, tmp_path, capsys, input_csv,
                                          golden_aud, golden_cla_path):
    from prompts import AGT_001, AUD_001, CLA_001

    _use_provider(monkeypatch, SequenceProvider([golden_aud, golden_cla_path]))
    rc = cli.main([
        "eval", "--input", str(input_csv), "--model", "m", "--no-save", "--json",
    ])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    assert payload["promptVersions"] == {
        "AUD-001": AUD_001.PROMPT_VERSION,
        "CLA-001": CLA_001.PROMPT_VERSION,
        "AGT-001": AGT_001.PROMPT_VERSION,
    }
    assert [r["agent"] for r in payload["runs"]] == ["AUD-001", "CLA-001"]


# ── Diagnostic à blanc --dry-run ─────────────────────────────────────────────

def _no_llm(monkeypatch):
    """Garde-fou : le LLM ne doit jamais être appelé en --dry-run."""
    monkeypatch.setattr(cli, "get_provider",
                        lambda **kw: pytest.fail("le LLM ne doit pas être appelé en --dry-run"))


def test_audit_dry_run_assembles_prompt_without_llm(monkeypatch, capsys, input_csv):
    """--dry-run montre CSV préparé, digest, prompt assemblé et tokens, sans LLM."""
    _no_llm(monkeypatch)
    rc = cli.main(["audit", str(input_csv), "--model", "m", "--dry-run"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "AUD-001 SYSTEM" in out and "AUD-001 USER" in out
    assert "Mesures automatiques" in out  # digest présent
    assert "Tokens d'entrée estimés" in out


def test_audit_dry_run_writes_no_files(monkeypatch, capsys, tmp_path, input_csv):
    _no_llm(monkeypatch)
    rc = cli.main(["audit", str(input_csv), "--model", "m", "--dry-run",
                   "--out-report", str(tmp_path / "rapport.md")])
    assert rc == cli.EXIT_OK
    assert not (tmp_path / "rapport.md").exists()  # aucun effet de bord


def test_audit_dry_run_json_payload(monkeypatch, capsys, input_csv):
    _no_llm(monkeypatch)
    rc = cli.main(["audit", str(input_csv), "--model", "m", "--dry-run", "--json"])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    assert payload["command"] == "audit" and payload["dryRun"] is True
    assert payload["ok"] is True and payload["exitCode"] == cli.EXIT_OK
    (aud,) = payload["agents"]
    assert aud["agent"] == "AUD-001"
    assert aud["preparedRows"] > 0
    assert aud["estimatedInputTokens"] > 0
    assert aud["prompts"]["system"] and aud["prompts"]["user"]
    assert aud["digest"]  # mesures automatiques injectées


def test_dry_run_needs_no_model(monkeypatch, capsys, input_csv):
    """Le dry-run n'appelle pas le LLM : aucune config modèle n'est exigée."""
    monkeypatch.setattr(cli, "DEFAULT_MODEL", "")
    _no_llm(monkeypatch)
    rc = cli.main(["audit", str(input_csv), "--dry-run", "--json"])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    assert payload["model"] is None


def test_classement_dry_run_json(monkeypatch, capsys, input_csv, plan_file):
    _no_llm(monkeypatch)
    rc = cli.main(["classement", str(input_csv), "--plan", str(plan_file),
                   "--model", "m", "--dry-run", "--json"])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    assert payload["command"] == "classement" and payload["dryRun"] is True
    (cla,) = payload["agents"]
    assert cla["agent"] == "CLA-001"
    assert cla["itemsTotal"] == 6
    assert cla["planKnown"] is True  # le plan est fourni à classement
    assert "Path;CurrentTitle;Date" in cla["prompts"]["user"]
    assert cla["estimatedInputTokens"] > 0


def test_classement_dry_run_needs_no_out(monkeypatch, capsys, input_csv, plan_file):
    """--out n'est pas requis en dry-run (aucun CSV produit)."""
    _no_llm(monkeypatch)
    rc = cli.main(["classement", str(input_csv), "--plan", str(plan_file),
                   "--model", "m", "--dry-run"])
    assert rc == cli.EXIT_OK


def test_classement_without_out_errors_when_real(monkeypatch, input_csv, plan_file):
    """Hors dry-run, --out reste obligatoire."""
    _use_provider(monkeypatch, FakeProvider(response="x"))
    rc = cli.main(["classement", str(input_csv), "--plan", str(plan_file), "--model", "m"])
    assert rc == cli.EXIT_INPUT_INVALID


def test_run_dry_run_both_agents_no_side_effects(monkeypatch, capsys, tmp_path, input_csv):
    _no_llm(monkeypatch)
    out_dir = tmp_path / "out"
    rc = cli.main(["run", str(input_csv), "--out-dir", str(out_dir),
                   "--model", "m", "--dry-run", "--json"])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    assert payload["command"] == "run" and payload["dryRun"] is True
    assert [a["agent"] for a in payload["agents"]] == ["AUD-001", "CLA-001"]
    # Le classement de `run` ne connaît pas encore le plan (audit non exécuté).
    assert payload["agents"][1]["planKnown"] is False
    assert not out_dir.exists()  # aucun répertoire de sortie créé


def test_dry_run_batch_size_aggregates_tokens(monkeypatch, capsys, input_csv, plan_file):
    """L'estimation agrège les lots ; le 1er lot sert d'aperçu de prompt."""
    _no_llm(monkeypatch)
    rc = cli.main(["classement", str(input_csv), "--plan", str(plan_file),
                   "--model", "m", "--batch-size", "2", "--dry-run", "--json"])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    cla = payload["agents"][0]
    assert cla["batches"] == 3  # 6 items / 2
    # Total = somme des lots → strictement supérieur à un seul lot.
    assert cla["estimatedInputTokens"] > cla["estimatedInputTokensPerBatch"]


# ── Estimation de coût € en --dry-run ────────────────────────────────────────

def test_dry_run_cost_for_known_cloud_model(monkeypatch, capsys, input_csv):
    """Un modèle cloud connu joint un coût d'entrée indicatif € au dry-run."""
    _no_llm(monkeypatch)
    rc = cli.main(["audit", str(input_csv), "--model", "claude-opus-4-8",
                   "--dry-run", "--json"])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    assert payload["estimatedCostEur"]["totalEur"] > 0
    assert payload["estimatedCostEur"]["label"] == "Claude Opus"
    cost = payload["agents"][0]["estimatedCostEur"]
    assert cost["totalEur"] == payload["estimatedCostEur"]["totalEur"]
    assert cost["priceDate"]  # grille datée


def test_dry_run_cost_text_output(monkeypatch, capsys, input_csv):
    _no_llm(monkeypatch)
    rc = cli.main(["audit", str(input_csv), "--model", "claude-opus-4-8", "--dry-run"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "coût d'entrée indicatif" in out and "€" in out


def test_dry_run_no_cost_for_local_model(monkeypatch, capsys, input_csv):
    """Rien pour les locaux : modèle servi via base_url → pas de coût."""
    _no_llm(monkeypatch)
    rc = cli.main(["audit", str(input_csv), "--model", "claude-opus-4-8",
                   "--base-url", "http://localhost:1234", "--dry-run", "--json"])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    assert payload["estimatedCostEur"] is None
    assert payload["agents"][0]["estimatedCostEur"] is None


def test_dry_run_no_cost_for_unknown_model(monkeypatch, capsys, input_csv):
    _no_llm(monkeypatch)
    rc = cli.main(["audit", str(input_csv), "--model", "modele-inconnu-xyz",
                   "--dry-run", "--json"])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    assert payload["estimatedCostEur"] is None


def test_run_dry_run_total_cost_sums_agents(monkeypatch, capsys, tmp_path, input_csv):
    """Le coût total agrège les deux agents (entrée AUD-001 + CLA-001)."""
    _no_llm(monkeypatch)
    rc = cli.main(["run", str(input_csv), "--out-dir", str(tmp_path / "out"),
                   "--model", "gpt-5.1", "--dry-run", "--json"])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    per_agent = sum(a["estimatedCostEur"]["totalEur"] for a in payload["agents"])
    # Égalité au centième d'euro près (chaque agent est arrondi séparément).
    assert payload["estimatedCostEur"]["totalEur"] == pytest.approx(per_agent, abs=1e-4)


# ── Budget de profondeur d'entrée ───────────────────────────────────────────

def test_audit_dry_run_budget_recommendation(monkeypatch, capsys, input_csv):
    """Le dry-run d'audit joint une recommandation d'échantillonnage par
    taille de vrac, avec l'estimation de tokens au réglage recommandé."""
    _no_llm(monkeypatch)
    rc = cli.main(["audit", str(input_csv), "--model", "m", "--dry-run", "--json"])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    budget = payload["agents"][0]["budgetRecommendation"]
    assert budget["itemCount"] == 6          # petit jeu de fixtures
    assert budget["tier"] == "petit"
    assert budget["currentSampleN"] == 5     # défaut moteur
    assert budget["recommendedSampleN"] == 0  # tout envoyer pour un petit vrac
    assert budget["matchesRecommendation"] is False
    assert budget["estimatedInputTokensAtRecommended"] > 0
    assert budget["tableDate"] and budget["rationale"]


def test_dry_run_budget_text_output(monkeypatch, capsys, input_csv):
    _no_llm(monkeypatch)
    rc = cli.main(["audit", str(input_csv), "--model", "m", "--dry-run"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Budget d'entrée" in out
    assert "vrac petit" in out


def test_dry_run_budget_matches_when_aligned(monkeypatch, capsys, input_csv):
    """En forçant --sample-n 0 sur le petit jeu, l'actuel = le recommandé."""
    _no_llm(monkeypatch)
    rc = cli.main(["audit", str(input_csv), "--model", "m", "--no-sample",
                   "--dry-run", "--json"])
    assert rc == cli.EXIT_OK
    payload, _ = _stdout_json(capsys)
    budget = payload["agents"][0]["budgetRecommendation"]
    assert budget["currentSampleN"] == 0
    assert budget["matchesRecommendation"] is True


def test_eval_sweep_sample_one_aud_run_per_value(monkeypatch, tmp_path, capsys,
                                                 input_csv, golden_aud):
    """--sweep-sample lance un run AUD-001 par valeur, chacun portant sa
    variante de préparation (sampleN) ; le rapport consigne le sweep."""
    import json

    _use_provider(monkeypatch, SequenceProvider([golden_aud, golden_aud]))
    results_dir = tmp_path / "results"
    rc = cli.main([
        "eval", "--input", str(input_csv), "--model", "m", "--agent", "aud",
        "--sweep-sample", "0", "--sweep-sample", "5",
        "--results-dir", str(results_dir),
    ])
    assert rc == cli.EXIT_OK
    report = json.loads(next(results_dir.glob("*.json")).read_text(encoding="utf-8"))
    aud_runs = [r for r in report["runs"] if r["agent"] == "AUD-001"]
    assert [r["prep"]["sampleN"] for r in aud_runs] == [0, 5]
    assert report["options"]["sweepSample"] == [0, 5]
    out = capsys.readouterr().out
    assert "[n=tous]" in out and "[n=5]" in out


def test_eval_sweep_clean_dates_two_variants(monkeypatch, tmp_path, capsys,
                                             input_csv, golden_aud):
    """--sweep-clean-dates produit deux variantes (avec / sans nettoyage)."""
    _use_provider(monkeypatch, SequenceProvider([golden_aud, golden_aud]))
    rc = cli.main([
        "eval", "--input", str(input_csv), "--model", "m", "--agent", "aud",
        "--sweep-clean-dates", "--no-save",
    ])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "dates=off" in out  # la variante sans nettoyage est étiquetée


def test_no_json_keeps_stdout_clean(monkeypatch, tmp_path, capsys, input_csv,
                                    golden_aud):
    """Sans --json, aucune sortie sur stdout pour audit (logs sur stderr)."""
    _use_provider(monkeypatch, FakeProvider(response=golden_aud))
    rc = cli.main([
        "audit", str(input_csv), "--out-plan", str(tmp_path / "plan.md"),
        "--model", "m",
    ])
    assert rc == cli.EXIT_OK
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "✓ CSV chargé" in captured.err


# ── Cohérence des options CLI ⇄ contrat moteur / front ────────────────────────

def _subcommand_options(name: str) -> set[str]:
    """Chaînes d'option (`--ref`…) exposées par une sous-commande de la CLI."""
    sub_action = next(
        a for a in cli.build_parser()._actions
        if isinstance(a, argparse._SubParsersAction)
    )
    return set(sub_action.choices[name]._option_string_actions.keys())


def _resolved_defaults(argv: list[str]) -> argparse.Namespace:
    """Options après résolution des défauts (sans fichier de config) — l'état que
    voit le moteur quand l'utilisateur ne passe rien d'autre que l'entrée."""
    args = cli.build_parser().parse_args(argv)
    cli._resolve_config_into_args(args, {})
    return args


def test_e7_classement_options_exposed_where_pertinent():
    """`--no-avis`/`--ref`/`--batch-size` partout où le classement est piloté."""
    for cmd in ("classement", "run"):
        opts = _subcommand_options(cmd)
        assert {"--no-avis", "--ref", "--batch-size"} <= opts, cmd
    eval_opts = _subcommand_options("eval")
    # eval objective le compromis Path/Ref via --cla-mode (matrice), pas --ref.
    assert {"--no-avis", "--batch-size", "--cla-mode"} <= eval_opts


def test_e7_brief_exposed_on_audit_run_eval():
    """`--brief` (mode plan seul) partout où un audit a lieu ; absent du
    classement (pas d'audit dans cette étape)."""
    for cmd in ("audit", "run", "eval"):
        assert "--brief" in _subcommand_options(cmd), cmd
    assert "--brief" not in _subcommand_options("classement")


def test_e7_prep_defaults_match_engine_contract():
    """Défauts de préparation de la CLI == contrat moteur (`PrepOptions` de l'API,
    partagé avec le front) : un même vrac part des mêmes options des deux côtés."""
    from api.schemas import PrepOptions
    prep = PrepOptions()
    args = _resolved_defaults(["audit", "x.csv"])
    assert (not args.no_filter_columns) is prep.filter_columns
    assert (not args.no_clean_dates) is prep.clean_dates
    assert (not args.no_sample) is prep.sample_items
    assert args.sample_n == prep.sample_items_n
    assert (not args.no_items) is prep.include_items
    assert bool(args.description) is prep.include_description
    assert (not args.no_auto_measures) is prep.auto_measures


def test_e7_classement_defaults_match_engine_contract():
    """Défauts de classement de la CLI == contrat moteur : avis activé, méthode
    Path, pas de découpage en lots (le front part des mêmes valeurs)."""
    from api.schemas import PrepOptions
    prep = PrepOptions()
    args = _resolved_defaults(["classement", "x.csv", "--plan", "p.md", "--out", "o.csv"])
    assert (not args.no_avis) is prep.classement_avis
    assert bool(args.ref) is prep.classement_ref
    assert (args.batch_size or 0) == 0


# ── reference-plans / plan de référence ──────────────────────────────────────

def _dry_run_json(capsys, argv):
    """Lance un dry-run --json et renvoie le payload (aucun appel LLM requis)."""
    rc = cli.main(argv)
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_audit_dry_run_no_reference_plan_unchanged(capsys, input_csv):
    _, payload = _dry_run_json(capsys, [
        "audit", str(input_csv), "--dry-run", "--json",
    ])
    user_msg = payload["agents"][0]["prompts"]["user"]
    assert "Plan de classement de référence" not in user_msg


def test_audit_reference_plan_file_block_injected(capsys, tmp_path, input_csv):
    """Fichier de bloc arborescence brut (toute extension hors .csv)."""
    plan = tmp_path / "ref.md"
    plan.write_text("```text\nFonds → F/\n  └── 1. Divers → 1_Divers/\n```", encoding="utf-8")
    _, payload = _dry_run_json(capsys, [
        "audit", str(input_csv), "--reference-plan-file", str(plan),
        "--dry-run", "--json",
    ])
    assert "1_Divers/" in payload["agents"][0]["prompts"]["user"]


def test_audit_reference_plan_file_csv_converted(capsys, tmp_path, input_csv):
    """Un CSV Resip « dossiers seuls » est converti en arborescence et injecté."""
    ref = tmp_path / "dossiers.csv"
    ref.write_text(
        "ID;ParentID;File;Content.DescriptionLevel;Content.Title;Content.StartDate;Content.EndDate\n"
        "1;;.;RecordGrp;Fonds test;;\n"
        "2;1;Fonds_test/Pilotage;RecordGrp;Pilotage;;\n",
        encoding="utf-8",
    )
    _, payload = _dry_run_json(capsys, [
        "audit", str(input_csv), "--reference-plan-file", str(ref),
        "--reference-mode", "conform", "--dry-run", "--json",
    ])
    user_msg = payload["agents"][0]["prompts"]["user"]
    assert "→ Pilotage/" in user_msg
    assert "Conformez-vous" in user_msg


def test_audit_reference_plan_file_csv_no_folders_exits_2(tmp_path, input_csv):
    ref = tmp_path / "items.csv"
    ref.write_text(
        "ID;ParentID;File;Content.DescriptionLevel;Content.Title;Content.StartDate;Content.EndDate\n"
        "1;;a.pdf;Item;a.pdf;2020;2020\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        cli.main([
            "audit", str(input_csv), "--reference-plan-file", str(ref), "--dry-run",
        ])
    assert exc.value.code == cli.EXIT_INPUT_INVALID
