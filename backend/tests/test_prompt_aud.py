"""Garde-fous du prompt AUD-001 — respect de l'ordre originel « by design » (1.1.0).

On ne teste pas la *qualité* du prompt (ça relève du harnais d'éval) mais
ses **invariants structurels** : le défaut conservateur ne doit pas régresser
silencieusement vers la conception libre, le gabarit doit rester parsable par
l'aval (`extract_plans`/`parse_plan_tree` + copie miroir TS), et les deux
variantes (rapport complet / plan seul) doivent partager le même bloc plan.
"""
from core.evals import _order_verdict  # parsing du verdict, source unique
from prompts import AUD_001


def test_version_carries_the_conservation_design():
    assert tuple(map(int, AUD_001.PROMPT_VERSION.split("."))) >= (1, 1, 0)


def test_plan_block_shared_and_parsable_in_both_variants():
    for sp in (AUD_001.SYSTEM_PROMPT, AUD_001.SYSTEM_PROMPT_BRIEF):
        # Bloc arborescence inchangé (contrat extract_plans/parse_plan_tree).
        assert "<!-- PLAN_STRUCTURE_START -->" in sp
        assert "<!-- PLAN_STRUCTURE_END -->" in sp
        # Verdict et écarts : hors des balises, dans le gabarit partagé.
        assert "Ordre existant :" in sp
        assert "Écarts à l'ordre existant" in sp


def test_conservation_is_the_default_not_an_option():
    for sp in (AUD_001.SYSTEM_PROMPT, AUD_001.SYSTEM_PROMPT_BRIEF):
        # L'ancien défaut (« Choisir librement ») a disparu…
        assert "Choisir librement" not in sp
        # …au profit de la dérivation de l'existant, verdict gradué à l'appui.
        assert "dérive de l'arborescence existante" in sp
        assert "PARTIELLEMENT STRUCTURÉ" in sp
        # La conception libre reste prévue — réservée au verdict ABSENT.
        assert "concevoir librement" in sp


def test_deviations_require_a_named_defect():
    for sp in (AUD_001.SYSTEM_PROMPT, AUD_001.SYSTEM_PROMPT_BRIEF):
        assert "liste fermée" in sp
        for defect in ("rubrique en doublon", "dossier fourre-tout",
                       "artefact de support", "profondeur excessive"):
            assert defect in sp
        # Les seuils restent explicites (leçon du 2026-07-05 : sans chiffre,
        # profondeur erratique et échappatoires vagues).
        assert "au plus 4 niveaux" in sp
        assert "au moins 10 fichiers" in sp
        assert "plus de 20 dossiers" in sp


def test_note_contextuelle_still_overrides():
    # Canal de la refonte libre (opt-out front) et des contraintes : la note
    # de l'archiviste doit primer sur les règles de conservation.
    for sp in (AUD_001.SYSTEM_PROMPT, AUD_001.SYSTEM_PROMPT_BRIEF):
        assert "note contextuelle" in sp
        assert "refonte libre" in sp


def test_gabarit_verdict_line_matches_eval_parser():
    # La ligne de verdict du gabarit doit être reconnue par le parseur de la
    # métrique d'éval — si le gabarit change de forme, ce test casse avant
    # qu'un run d'éval ne rende silencieusement « non mesurable ».
    sample = "**Ordre existant :** STRUCTURÉ — logique par service."
    assert AUD_001.SYSTEM_PROMPT.count("**Ordre existant :**") == 1
    assert _order_verdict(sample) == "STRUCTURÉ"
