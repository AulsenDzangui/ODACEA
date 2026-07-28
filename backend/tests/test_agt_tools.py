"""Outils de requête lecture seule de l'agent — testés sans LLM.

Les chiffres attendus sont recalculés « à la main » sur la fixture
`archifiltre_small.csv` (10 lignes : racine, 3 dossiers, 6 fichiers) : les
outils doivent renvoyer des totaux **exacts** (critère d'acceptation).
"""
import pandas as pd

from core import agt_tools
from core.agt_tools import (
    PAGE_SIZE,
    chercher,
    compter,
    echantillonner,
    filtrer_items,
    lister_dossier,
    mots_frequents,
    stats,
)

# ── chercher ─────────────────────────────────────────────────────────────────

def test_chercher_keyword(small_df):
    out = chercher(small_df, ["eleves"])
    assert out["total"] == 2
    assert all(r["type"] == "fichier" for r in out["resultats"])


def test_chercher_accents_et_casse(small_df):
    """Insensible à la casse et aux accents : « Élèves » trouve « eleves »."""
    assert chercher(small_df, ["Élèves"])["total"] == 2


def test_chercher_et_logique(small_df):
    """Plusieurs mots-clés = ET : chacun réduit le résultat."""
    assert chercher(small_df, ["eleves", "2023"])["total"] == 1


def test_chercher_trouve_les_dossiers(small_df):
    """La recherche couvre fichiers ET dossiers (le dossier `cantine` + ses 2 fichiers)."""
    out = chercher(small_df, ["cantine"])
    assert out["total"] == 3
    assert sorted(r["type"] for r in out["resultats"]) == ["dossier", "fichier", "fichier"]


def test_chercher_chaine_unique_acceptee(small_df):
    """Tolérance : une chaîne (au lieu d'une liste) est découpée en mots."""
    assert chercher(small_df, "liste eleves")["total"] == 2


def test_chercher_arguments_invalides(small_df):
    assert "erreur" in chercher(small_df, [])
    assert "erreur" in chercher(small_df, [42])  # type: ignore[list-item]


def test_chercher_page_inexistante(small_df):
    out = chercher(small_df, ["eleves"], page=5)
    assert "erreur" in out
    assert out["total"] == 2  # le total exact accompagne même l'erreur


# ── lister_dossier ───────────────────────────────────────────────────────────

def test_lister_racine(small_df):
    out = lister_dossier(small_df, ".")
    assert out["totalSousDossiers"] == 3
    assert {d["chemin"] for d in out["sousDossiers"]} == {"inscriptions", "cantine", "divers"}
    assert all(d["fichiers"] == 2 for d in out["sousDossiers"])
    assert out["totalFichiers"] == 0  # aucun fichier directement à la racine


def test_lister_sous_dossier(small_df):
    out = lister_dossier(small_df, "cantine")
    assert out["totalFichiers"] == 2
    assert out["totalSousDossiers"] == 0
    assert {f["chemin"] for f in out["fichiers"]} == {
        "cantine/menus_janvier.docx",
        "cantine/facture_traiteur_2021.pdf",
    }


def test_lister_dossier_casse_indifferente(small_df):
    assert lister_dossier(small_df, "CANTINE")["totalFichiers"] == 2


def test_lister_dossier_introuvable_suggere(small_df):
    out = lister_dossier(small_df, "cantin")
    assert "erreur" in out
    assert "cantine" in out.get("suggestions", [])


# ── filtre structuré / compter ───────────────────────────────────────────────

def test_compter_sans_filtre(small_df):
    assert compter(small_df)["total"] == 6


def test_compter_par_extension(small_df):
    assert compter(small_df, {"extension": "pdf"})["total"] == 1
    assert compter(small_df, {"extension": ".XLSX"})["total"] == 2


def test_compter_par_mots_cles(small_df):
    assert compter(small_df, {"mots_cles": ["menus"]})["total"] == 1


def test_compter_par_dossier(small_df):
    assert compter(small_df, {"dossier": "divers"})["total"] == 2


def test_compter_par_annees(small_df):
    # Dates des 6 Items : 2022, 2023, 2022, 2021, 2022, 2019.
    assert compter(small_df, {"annee_min": 2022})["total"] == 4
    assert compter(small_df, {"annee_max": 2019})["total"] == 1
    assert compter(small_df, {"annee_min": 2021, "annee_max": 2021})["total"] == 1


def test_compter_filtres_combines(small_df):
    out = compter(small_df, {"dossier": "inscriptions", "extension": "xlsx", "annee_min": 2023})
    assert out["total"] == 1


def test_compter_repartition_extensions(small_df):
    out = compter(small_df)
    assert out["parExtension"]["xlsx"] == 2


def test_filtre_cle_inconnue(small_df):
    out = compter(small_df, {"extention": "pdf"})
    assert "erreur" in out
    assert "extention" in out["erreur"]
    assert "extension" in out["erreur"]  # les clés admises sont listées


def test_filtre_types_invalides(small_df):
    assert "erreur" in compter(small_df, {"mots_cles": [1]})
    assert "erreur" in compter(small_df, {"extension": 3})
    assert "erreur" in compter(small_df, {"annee_min": "2020"})
    assert "erreur" in filtrer_items(small_df, "pdf")  # type: ignore[arg-type]


# ── echantillonner ───────────────────────────────────────────────────────────

def test_echantillonner_deterministe(small_df):
    a = echantillonner(small_df, n=3)
    b = echantillonner(small_df, n=3)
    assert a == b
    assert a["total"] == 6
    assert a["n"] == 3


def test_echantillonner_moins_que_n(small_df):
    out = echantillonner(small_df, {"extension": "pdf"}, n=5)
    assert out["n"] == out["total"] == 1


def test_echantillonner_n_invalide(small_df):
    assert "erreur" in echantillonner(small_df, n=0)
    assert "erreur" in echantillonner(small_df, n=True)


def test_echantillonner_n_borne(small_df):
    assert echantillonner(small_df, n=500)["n"] <= PAGE_SIZE


# ── stats ────────────────────────────────────────────────────────────────────

def test_stats_extension(small_df):
    out = stats(small_df, "extension")
    assert out["total"] == 6
    assert out["valeurs"] == {"xlsx": 2, "docx": 1, "pdf": 1, "jpg": 1, "doc": 1}


def test_stats_periode(small_df):
    out = stats(small_df, "periode")
    assert out["valeurs"] == {"2022": 3, "2023": 1, "2021": 1, "2019": 1}


def test_stats_dossier(small_df):
    out = stats(small_df, "dossier")
    assert out["valeurs"] == {"inscriptions": 2, "cantine": 2, "divers": 2}


def test_stats_par_invalide(small_df):
    assert "erreur" in stats(small_df, "taille")


def test_stats_troncature_totaux_exacts(small_df):
    """Au-delà de MAX_BUCKETS valeurs, l'agrégat « (autres) » préserve le total."""
    df = small_df.copy()
    rows = []
    for i in range(30):
        rows.append({
            "ID": str(100 + i), "ParentID": "1", "File": f"divers/f{i}.ext{i}",
            "Content.DescriptionLevel": "Item", "Content.Title": f"f{i}",
            "Content.StartDate": "2020-01-01", "Content.EndDate": "2020-01-01",
        })
    df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    out = stats(df, "extension")
    assert out["total"] == 36
    assert sum(out["valeurs"].values()) == 36
    assert "(autres)" in out["valeurs"]


# ── mots_frequents ───────────────────────────────────────────────────────────

def test_mots_frequents_comptes_exacts(small_df):
    """Fréquence exacte sur tout le vrac : l'occurrence d'un terme est le
    nombre de fichiers dont le chemin ou le titre le porte."""
    out = mots_frequents(small_df)
    assert out["total"] == 6
    assert out["termes"]["eleves"] == 2      # 2 fichiers « liste eleves »
    assert out["termes"]["cantine"] == 2     # segment de dossier, 2 fichiers
    assert out["termes"]["facture"] == 1
    assert out["termesDistincts"] == 13
    assert out["tronque"] is False


def test_mots_frequents_titre_ne_double_pas(small_df):
    """Le titre recopie souvent le nom du fichier : un terme n'est compté
    qu'une fois par fichier (« liste » vaut 2 fichiers, pas 4 occurrences)."""
    assert mots_frequents(small_df)["termes"]["liste"] == 2


def test_mots_frequents_extensions_exclues(small_df):
    """Les extensions ne sont pas des thèmes (couvertes par stats(extension))."""
    termes = mots_frequents(small_df)["termes"]
    assert "xlsx" not in termes
    assert "pdf" not in termes


def test_mots_frequents_nombres_exclus(small_df):
    """Les nombres (années, versions) ne sont pas des termes (stats(periode))."""
    termes = mots_frequents(small_df)["termes"]
    assert "2022" not in termes
    assert "001" not in termes


def test_mots_frequents_stopwords_et_accents(small_df):
    """Mots vides français écartés ; repli casse/accents sur les tokens."""
    df = small_df.copy()
    df.loc[df["File"] == "divers/note service.doc", "Content.Title"] = (
        "Note pour les Élèves de la cantine"
    )
    termes = mots_frequents(df)["termes"]
    assert termes["eleves"] == 3       # « Élèves » rejoint « eleves »
    assert termes["cantine"] == 3
    assert "les" not in termes and "pour" not in termes


def test_mots_frequents_filtre(small_df):
    """Le filtre structuré restreint le périmètre ; erreur passée telle quelle."""
    out = mots_frequents(small_df, filtre={"dossier": "cantine"})
    assert out["total"] == 2
    assert out["termes"]["cantine"] == 2
    assert "eleves" not in out["termes"]
    assert "erreur" in mots_frequents(small_df, filtre={"taille": 3})


def test_mots_frequents_top_n_deterministe(small_df):
    """Top-N borné, tri déterministe : fréquence décroissante puis alphabétique."""
    out = mots_frequents(small_df, n=5)
    assert list(out["termes"]) == ["cantine", "divers", "eleves", "inscriptions", "liste"]
    assert out["n"] == 5
    assert out["tronque"] is True
    assert out["termesDistincts"] == 13  # le total exact accompagne la troncature


def test_mots_frequents_n_invalide_et_borne(small_df):
    assert "erreur" in mots_frequents(small_df, n=0)
    assert "erreur" in mots_frequents(small_df, n="dix")  # type: ignore[arg-type]
    assert mots_frequents(small_df, n=5000)["n"] <= agt_tools.MAX_TERMES


def test_page_size_borne_les_listes(small_df):
    """Les listes sont bornées par PAGE_SIZE, le total reste exact."""
    rows = [
        {
            "ID": str(100 + i), "ParentID": "1", "File": f"divers/rapport_{i}.pdf",
            "Content.DescriptionLevel": "Item", "Content.Title": f"rapport {i}",
            "Content.StartDate": "2020-01-01", "Content.EndDate": "2020-01-01",
        }
        for i in range(50)
    ]
    df = pd.concat([small_df, pd.DataFrame(rows)], ignore_index=True)
    out = chercher(df, ["rapport"])
    assert out["total"] == 50
    assert len(out["resultats"]) == PAGE_SIZE
    assert out["tronque"] is True
    page2 = chercher(df, ["rapport"], page=2)
    assert len(page2["resultats"]) == 10


def test_resultats_metadonnees_seules(small_df):
    """Les payloads d'outils ne portent que chemin/titre/type/date."""
    out = chercher(small_df, ["eleves"])
    assert set(out["resultats"][0]) == {"chemin", "titre", "type", "date"}
    assert set(agt_tools._row_payload(small_df.iloc[2])) == {"chemin", "titre", "type", "date"}
