"""Tests du harnais d'évaluation des prompts.

Trois volets, tous déterministes (aucun appel réseau) :
  * métriques AUD-001 — `audit_metrics` sur le golden file et sur des
    rapports synthétiques (conforme au gabarit, dégradé, brief) ;
  * compteurs CLA-001 — `classement_metrics` sur les stats produites par
    `convert_classement_to_resip`, y compris les garde-fous (extension corrigée,
    item non classé, cible inconnue, Ref non résolue) ;
  * exactitude AGT-001 — `agent_case_metrics`/`agent_run_metrics` sur des
    événements de tour d'agent fabriqués : équivalence **sémantique** des
    filtres émis, cible de classement normalisée, total exact dans la réponse ;
  * mise en forme — `format_table` / `format_eval_tables` (tableau lisible).
"""

import pandas as pd

from core.audit_scan import scan_metadata
from core.csv_handler import convert_classement_to_resip, extract_csv_from_response
from core.evals import (
    agent_case_metrics,
    agent_run_metrics,
    audit_metrics,
    classement_metrics,
    conservation_label,
    format_eval_tables,
    format_table,
    plan_shape,
)

# ── plan_shape ────────────────────────────────────────────────────────────────

def test_plan_shape_empty_tree():
    assert plan_shape({}) == {"folders": 0, "depth": 0, "maxWidth": 0, "leaves": 0}


def test_plan_shape_golden_tree(plan_valide):
    from core.csv_handler import parse_plan_tree

    shape = plan_shape(parse_plan_tree(plan_valide))
    # AFFAIRES_SCOLAIRES > {1_Inscriptions, 2_Cantine > {2-1, 2-2}, 3_Vie_scolaire}
    assert shape == {"folders": 6, "depth": 3, "maxWidth": 3, "leaves": 4}


# ── audit_metrics ─────────────────────────────────────────────────────────────

def test_audit_metrics_golden(golden_aud, small_df):
    m = audit_metrics(golden_aud, scan=scan_metadata(small_df))
    assert m["planExtracted"] is True
    assert m["planStructureBlock"] is True
    assert m["planTreeParsed"] is True
    assert m["planFolders"] == 6
    assert m["planDepth"] == 3
    assert m["planMaxWidth"] == 3
    assert m["planLeaves"] == 4
    # Le golden ne suit pas le gabarit strict 1.1–1.5 : sections absentes,
    # volumétrie hors format imposé → non mesurable (None), signal en soi.
    assert m["gabaritSectionsPresent"] == []
    assert m["gabaritComplete"] is False
    assert m["volumetryReported"] is None
    assert m["volumetryMatches"] is None


def _conforming_report(plan_block: str, items: int, rg: int, depth: int) -> str:
    return f"""# RAPPORT D'AUDIT ARCHIVISTIQUE

## PARTIE 1 — ÉTAT DES LIEUX

### 1.1 Volumétrie

Items : {items} | RecordGrp : {rg} | Profondeur : {depth} niveaux

### 1.2 Arborescence et nommage

RAS.

### 1.3 Formats à risque

Aucun format à risque détecté.

### 1.4 Doublons sémantiques

Aucun doublon sémantique détecté.

### 1.5 Données personnelles (RGPD)

Aucune donnée personnelle identifiée.

## PARTIE 2 — PLAN DE CLASSEMENT

{plan_block}

## PARTIE 3 — NOTES POUR L'ARCHIVISTE

1. RAS.
"""


def test_audit_metrics_conforming_gabarit(golden_aud, small_df):
    # Reprend le bloc plan du golden, dans un rapport au gabarit strict avec la
    # volumétrie exacte du scan : tout doit être vert.
    plan_block = golden_aud[golden_aud.index("<!-- PLAN_STRUCTURE_START -->"):
                            golden_aud.index("<!-- PLAN_STRUCTURE_END -->")]
    scan = scan_metadata(small_df)
    v = scan["volumetry"]
    report = _conforming_report(plan_block, v["items"], v["recordGrps"], v["maxDepth"])
    m = audit_metrics(report, scan=scan)
    assert m["gabaritSectionsPresent"] == ["1.1", "1.2", "1.3", "1.4", "1.5"]
    assert m["gabaritComplete"] is True
    assert m["volumetryReported"] == {
        "items": v["items"], "recordGrps": v["recordGrps"], "maxDepth": v["maxDepth"],
    }
    assert m["volumetryMatches"] is True


def test_audit_metrics_volumetry_mismatch(golden_aud, small_df):
    # Le modèle a « halluciné » des chiffres : ligne au gabarit mais valeurs fausses.
    plan_block = golden_aud[golden_aud.index("<!-- PLAN_STRUCTURE_START -->"):
                            golden_aud.index("<!-- PLAN_STRUCTURE_END -->")]
    report = _conforming_report(plan_block, items=999, rg=4, depth=2)
    m = audit_metrics(report, scan=scan_metadata(small_df))
    assert m["volumetryReported"]["items"] == 999
    assert m["volumetryMatches"] is False


def test_audit_metrics_brief_neutralises_gabarit(golden_aud, small_df):
    m = audit_metrics(golden_aud, scan=scan_metadata(small_df), brief=True)
    assert m["gabaritSectionsPresent"] is None
    assert m["gabaritComplete"] is None
    # Les métriques de plan restent mesurées en brief.
    assert m["planTreeParsed"] is True


def test_audit_metrics_degraded_response():
    m = audit_metrics("Bonjour, je ne peux pas analyser ce fichier.")
    assert m["planExtracted"] is False
    assert m["planStructureBlock"] is False
    assert m["planTreeParsed"] is False
    assert m["planFolders"] == 0
    assert m["volumetryMatches"] is None
    # Sans scan ni arbre : conservation et verdict non mesurables.
    assert m["ordreExistant"] is None
    assert m["sourceFoldersTotal"] is None
    assert m["sourceFoldersRetained"] is None
    assert m["sourceRetainedPct"] is None
    assert m["planFoldersCreated"] is None


# ── Conservation de l'ordre existant (respect de l'ordre originel) ────────────

def test_conservation_label_folds_prefixes_and_accents():
    # Nom technique du plan (translittéré) ⇄ dossier source accentué.
    assert conservation_label("1_Marches_publics") == conservation_label("Marchés publics")
    # Préfixe ordinal des dossiers sources : `1. `, `1.2. `, `3) `.
    assert conservation_label("1. Comptabilité") == "comptabilite"
    assert conservation_label("1.2. Comptabilité") == "comptabilite"
    # Un dossier-année n'est jamais tronqué (pas de séparateur `.`/`)`).
    assert conservation_label("2024 factures") == "2024 factures"
    assert conservation_label("2024") == "2024"


def test_conservation_label_folds_renames_observed_on_demo_corpus():
    """Renommages triviaux mesurés le 2026-07-09 : sans ces replis, des
    conservations réelles comptaient comme créations (13 % mesurés pour ~30 %
    réels sur le corpus démo)."""
    # Tirets ⇄ underscores ⇄ espaces.
    assert conservation_label("Inscriptions 2022-2023") == conservation_label(
        "1-2_Inscriptions_2022_2023"
    )
    # Élision française (`d'`) écartée.
    assert conservation_label("Conseils d'ecole") == conservation_label("Conseils_ecole")
    # Ordre des mots indifférent (sac de mots trié).
    assert conservation_label("ATSEM - Personnel") == conservation_label("Personnel_ATSEM")
    assert conservation_label("Periscolaire ALSH garderie") == conservation_label(
        "Periscolaire_garderie_ALSH"
    )
    # Un chiffre isolé reste discriminant : Tome 2 ≠ Tome 3.
    assert conservation_label("Tome 2") != conservation_label("Tome 3")


def test_audit_metrics_conservation_on_golden(golden_aud, small_df):
    m = audit_metrics(golden_aud, scan=scan_metadata(small_df))
    # Sources non vides : inscriptions, cantine, divers. Plan golden : la racine
    # AFFAIRES_SCOLAIRES est exclue ; Inscriptions et Cantine sont conservés,
    # Menus / Factures / Vie_scolaire sont des créations, divers disparaît.
    assert m["sourceFoldersTotal"] == 3
    assert m["sourceFoldersRetained"] == 2
    assert m["sourceRetainedPct"] == 66.7
    assert m["planFoldersCreated"] == 3
    # Golden antérieur au gabarit 1.1.0 : pas de verdict — non mesurable.
    assert m["ordreExistant"] is None


def test_audit_metrics_order_verdict_parsed(golden_aud, small_df):
    report = golden_aud.replace(
        "### Plan retenu — Fonctionnel",
        "### Plan retenu — Dérivé de l'ordre existant\n\n"
        "**Ordre existant :** PARTIELLEMENT STRUCTURÉ — un socle net "
        "(inscriptions, cantine) côtoie un fourre-tout (divers).",
    )
    m = audit_metrics(report, scan=scan_metadata(small_df))
    assert m["ordreExistant"] == "PARTIELLEMENT STRUCTURÉ"


def test_audit_metrics_order_verdict_tolerant_to_case_and_accents():
    # Un modèle local écrit parfois « structure » sans accent ni majuscules :
    # le verdict est reconnu sur forme repliée, restitué en canonique.
    m = audit_metrics("**Ordre existant :** structure — logique claire.")
    assert m["ordreExistant"] == "STRUCTURÉ"


def test_audit_metrics_conservation_none_for_legacy_scan(golden_aud):
    # Un scan historisé avant la métrique (sans `sourceFolders`) reste lisible.
    m = audit_metrics(golden_aud, scan={"volumetry": {"items": 0, "recordGrps": 0, "maxDepth": 0}})
    assert m["sourceFoldersTotal"] is None
    assert m["planFoldersCreated"] is None


# ── classement_metrics ────────────────────────────────────────────────────────

def test_classement_metrics_golden_path(golden_cla_path, small_df, plan_valide):
    df_llm = extract_csv_from_response(golden_cla_path, id_col="Path")
    _, _, stats = convert_classement_to_resip(df_llm, small_df, plan_valide)
    m = classement_metrics(stats)
    assert m["planMatches"] is True
    assert m["itemsTotal"] == 6
    assert m["itemsClassified"] == 6
    assert m["itemsUnclassified"] == 0
    assert m["classifiedPct"] == 100.0
    assert m["itemsMalformed"] == 0
    assert m["extensionsFixed"] == 0
    assert m["targetsUnknown"] == 0
    assert m["pathsNotFound"] == 0
    assert m["refsUnresolved"] == 0


def test_classement_counters_at_source(small_df, plan_valide):
    """Chaque garde-fou incrémente son compteur — plus de re-parsing des
    messages d'avertissement nécessaire pour agréger."""
    df_llm = pd.DataFrame(
        [
            # OK.
            ["inscriptions/liste_eleves_2022.xlsx", "1_Inscriptions", "2022-09-01_liste_VF.xlsx"],
            # Cible vide → targetsUnknown (item perdu pour le classement).
            ["inscriptions/liste eleves 2023 v2.xlsx", "", "2023-09-04_liste_V02.xlsx"],
            # Extension convertie à tort par le LLM → extensionsFixed.
            ["cantine/menus_janvier.docx", "2-1_Menus", "2022-01-03_menus_VF.pdf"],
            ["cantine/facture_traiteur_2021.pdf", "2-2_Factures", "2021-11-15_facture_VF.pdf"],
            ["divers/photo_kermesse_001.jpg", "3_Vie_scolaire", "2022-06-25_photo_VF.jpg"],
            # Chemin halluciné, absent de l'original → pathsNotFound.
            ["fantome/inconnu.pdf", "1_Inscriptions", "2020-01-01_inconnu_VF.pdf"],
            # « divers/note service.doc » absent de la sortie → itemsUnclassified.
        ],
        columns=["Path", "TargetFolder", "NewTitle"],
    )
    _, warnings, stats = convert_classement_to_resip(df_llm, small_df, plan_valide)
    m = classement_metrics(stats)
    assert m["itemsTotal"] == 6
    assert m["itemsClassified"] == 4
    assert m["itemsUnclassified"] == 1
    assert m["extensionsFixed"] == 1
    assert m["targetsUnknown"] == 1
    assert m["pathsNotFound"] == 1
    assert m["refsUnresolved"] == 0
    # Les avertissements texte restent émis en parallèle des compteurs.
    assert any("non classé" in w for w in warnings)
    assert any("TargetFolder inconnu" in w for w in warnings)


def test_classement_counters_ref_unresolved(small_df, plan_valide):
    """Mode Ref : une référence hallucinée → refsUnresolved + pathsNotFound."""
    df_llm = pd.DataFrame(
        [
            ["1", "1_Inscriptions", "2022-09-01_liste_VF.xlsx"],
            ["2", "1_Inscriptions", "2023-09-04_liste_V02.xlsx"],
            ["3", "2-1_Menus", "2022-01-03_menus_VF.docx"],
            ["4", "2-2_Factures", "2021-11-15_facture_VF.pdf"],
            ["5", "3_Vie_scolaire", "2022-06-25_photo_VF.jpg"],
            ["99", "3_Vie_scolaire", "2019-01-10_note_VF.doc"],  # Ref hallucinée
        ],
        columns=["Ref", "TargetFolder", "NewTitle"],
    )
    _, _, stats = convert_classement_to_resip(df_llm, small_df, plan_valide)
    m = classement_metrics(stats)
    assert m["refsUnresolved"] == 1
    assert m["pathsNotFound"] == 1  # le Path vide réhydraté est introuvable
    assert m["itemsUnclassified"] == 1  # note service.doc jamais référencée
    assert m["itemsClassified"] == 5


# ── agent_case_metrics / agent_run_metrics ────────────────────────────────────

def _agent_events(calls, answer, steps=None):
    """Fabrique les événements d'un tour d'agent : (name, arguments, result)*
    puis l'événement final — la forme produite par `core.agt_agent.agent_turn`."""
    events = []
    for i, (name, arguments, result) in enumerate(calls, start=1):
        events.append({"type": "tool", "step": i, "name": name, "arguments": arguments})
        events.append({"type": "toolResult", "step": i, "name": name, "result": result})
    events.append({
        "type": "final", "answer": answer,
        "steps": steps if steps is not None else len(calls) + 1, "usage": None,
    })
    return events


REQ_PDF = {
    "type": "requete", "outils": ["compter"],
    "filtre": {"extension": "pdf"}, "verifierTotal": True,
}


def test_agent_case_requete_reussie(small_df):
    events = _agent_events(
        [("compter", {"filtre": {"extension": "pdf"}}, {"total": 1})],
        "Le vrac compte 1 fichier PDF.",
    )
    m = agent_case_metrics(events, REQ_PDF, small_df)
    assert m["reussi"] is True
    assert m["outilAttendu"] and m["filtreEquivalent"] and m["reponseExacte"]
    assert m["steps"] == 2


def test_agent_case_filtre_equivalence_semantique(small_df):
    """L'équivalence est jugée sur la **sélection** produite, pas sur la forme :
    sur la fixture, {"mots_cles": ["facture"]} sélectionne exactement le même
    fichier unique que le golden {"extension": "pdf"}."""
    events = _agent_events(
        [("compter", {"filtre": {"mots_cles": ["facture"]}}, {"total": 1})],
        "1 fichier.",
    )
    assert agent_case_metrics(events, REQ_PDF, small_df)["filtreEquivalent"] is True


def test_agent_case_filtre_et_reponse_faux(small_df):
    events = _agent_events(
        [("compter", {"filtre": {"extension": "xlsx"}}, {"total": 2})],
        "Il y a 2 fichiers.",
    )
    m = agent_case_metrics(events, REQ_PDF, small_df)
    assert m["outilAttendu"] is True
    assert m["filtreEquivalent"] is False
    assert m["reponseExacte"] is False  # le total exact du golden (1) est absent
    assert m["reussi"] is False


def test_agent_case_sans_outil(small_df):
    """Un chiffre juste sans appel d'outil n'est pas un cas réussi (le principe
    « jamais de chiffre de tête » est précisément ce que l'éval mesure)."""
    events = _agent_events([], "Je pense qu'il y a 1 PDF.")
    m = agent_case_metrics(events, REQ_PDF, small_df)
    assert m["outilAttendu"] is False
    assert m["reponseExacte"] is True
    assert m["reussi"] is False


def test_agent_case_chercher_chaine_traduite(small_df):
    """`chercher` (arguments propres, chaîne tolérée) est traduit en filtre
    structuré pour l'équivalence."""
    attendu = {"type": "requete", "outils": ["chercher"],
               "filtre": {"mots_cles": ["eleves"]}}
    events = _agent_events(
        [("chercher", {"mots_cles": "eleves"}, {"total": 2})], "2 listes."
    )
    assert agent_case_metrics(events, attendu, small_df)["reussi"] is True


def test_agent_run_metrics_agrege():
    cases = [
        {"reussi": True, "outilAttendu": True, "filtreEquivalent": True,
         "reponseExacte": True, "steps": 2},
        {"reussi": False, "outilAttendu": False, "filtreEquivalent": False,
         "reponseExacte": None, "steps": 4},
        {"reussi": False, "error": "timeout"},
    ]
    m = agent_run_metrics(cases)
    assert m["cases"] == 3 and m["reussis"] == 1
    assert m["exactitudePct"] == 33.3
    assert m["outilAttendu"] == {"ok": 1, "mesures": 2}
    assert m["reponseExacte"] == {"ok": 1, "mesures": 1}
    assert m["stepsMoyen"] == 3.0
    assert m["erreurs"] == 1


def test_agent_run_metrics_vide():
    m = agent_run_metrics([])
    assert m["cases"] == 0 and m["exactitudePct"] is None


# ── Tableau lisible ───────────────────────────────────────────────────────────

def test_format_table_aligns_columns():
    out = format_table(["a", "bb"], [["xxx", "y"], ["z", "wwww"]])
    lines = out.split("\n")
    assert lines[0].startswith("a    bb")
    assert set(lines[1]) <= {"-", " "}
    assert len(lines) == 4


def test_format_eval_tables_renders_runs_and_errors(golden_aud, golden_cla_path,
                                                    small_df, plan_valide):
    scan = scan_metadata(small_df)
    df_llm = extract_csv_from_response(golden_cla_path, id_col="Path")
    _, _, stats = convert_classement_to_resip(df_llm, small_df, plan_valide)
    runs = [
        {"dataset": "small.csv", "model": "modele-a", "agent": "AUD-001",
         "brief": False, "mode": None, "durationS": 12.3,
         "usage": {"total_tokens": 1200}, "metrics": audit_metrics(golden_aud, scan=scan),
         "error": None},
        {"dataset": "small.csv", "model": "modele-a", "agent": "CLA-001",
         "brief": False, "mode": "path", "durationS": 20.0,
         "usage": None, "metrics": classement_metrics(stats), "error": None},
        {"dataset": "small.csv", "model": "modele-b", "agent": "CLA-001",
         "brief": False, "mode": "ref", "durationS": None,
         "usage": None, "metrics": None, "error": "connexion refusée"},
    ]
    out = format_eval_tables(runs)
    assert "AUD-001 — audit" in out
    assert "CLA-001 — classement" in out
    assert "6/6" in out          # classés
    assert "modele-a" in out
    assert "ERREUR : connexion refusée" in out
    # Colonnes conservation : golden sans verdict (—) mais conservation mesurée.
    assert "conserv." in out
    assert "2/3 (66.7%)" in out


def test_format_eval_tables_agt(small_df):
    """Le tableau AGT-001 : exactitude agrégée + dimensions, erreurs affichées."""
    events = _agent_events(
        [("compter", {"filtre": {"extension": "pdf"}}, {"total": 1})],
        "1 fichier PDF.",
    )
    case_ok = {"id": "pdf", **agent_case_metrics(events, REQ_PDF, small_df)}
    case_ko = {"id": "down", "reussi": False, "error": "timeout"}
    runs = [
        {"dataset": "small.csv", "model": "modele-a", "agent": "AGT-001",
         "brief": False, "mode": "native", "durationS": 4.2,
         "usage": {"total_tokens": 500},
         "metrics": agent_run_metrics([case_ok, case_ko]), "error": None},
        {"dataset": "small.csv", "model": "modele-b", "agent": "AGT-001",
         "brief": False, "mode": "json", "durationS": None,
         "usage": None, "metrics": None, "error": "connexion refusée"},
    ]
    out = format_eval_tables(runs)
    assert "AGT-001 — agent" in out
    assert "1/2 (50.0%)" in out
    assert "ERREUR : connexion refusée" in out


def test_format_eval_tables_empty():
    assert format_eval_tables([]) == "(aucun run)"
