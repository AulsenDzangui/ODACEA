"""
Version réduite (~80 fichiers) de l'arborescence bureautique fictive,
calibrée pour tester l'app sur un modèle local 14B (Qwen, Mistral, etc.).

Conserve un échantillon de chaque pattern de désordre du script principal :
doublons, versions cumulées, naming scanner, casse/accents incohérents,
mauvais classement, données nominatives mal placées, dossier vide.

Service simulé : Mairie de Saint-Genis-le-Champêtre — Affaires scolaires
                 et périscolaire (sept. 2018 → juin 2024).

Le dossier généré est différent de la version complète pour pouvoir
coexister :
    demo_data/Mairie_Saint-Genis_Affaires_Scolaires_SMALL/

Usage :
    python scripts/generate_demo_tree_small.py
"""

from __future__ import annotations

import os
import random
import shutil
from datetime import datetime
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "demo_data" / "Mairie_Saint-Genis_Affaires_Scolaires_SMALL"


FILES: list[tuple[str, str]] = []


# ---------------------------------------------------------------------------
# 01_Inscriptions scolaires/  — 1 année par sous-dossier, 1 série de versions
# ---------------------------------------------------------------------------
FILES += [
    ("01_Inscriptions scolaires/Inscriptions 2022-2023/Liste eleves rentree 2022.xlsx", "2022-09-01"),
    ("01_Inscriptions scolaires/Inscriptions 2022-2023/derogations.pdf", "2022-08-22"),
    ("01_Inscriptions scolaires/Inscriptions 2022-2023/derogations - Copie.pdf", "2022-08-22"),
    ("01_Inscriptions scolaires/Inscriptions 2023/Liste eleves rentree 2022.xlsx", "2022-09-01"),  # mauvais dossier
    ("01_Inscriptions scolaires/Inscriptions 2023/Liste eleves CP rentree 2023.xlsx", "2023-09-04"),
    # Série de versions cumulées
    ("01_Inscriptions scolaires/courrier parents - rentree 2024.docx", "2024-06-20"),
    ("01_Inscriptions scolaires/courrier parents - rentree 2024 VF.docx", "2024-06-25"),
    ("01_Inscriptions scolaires/courrier parents - rentree 2024 FINAL_VRAI.docx", "2024-06-27"),
    ("01_Inscriptions scolaires/SCAN_0034.pdf", "2021-09-12"),
    ("01_Inscriptions scolaires/aaaa.pdf", "2020-11-03"),
]


# ---------------------------------------------------------------------------
# Conseils d'ecole/  — 2 écoles, casse incohérente, doublons
# ---------------------------------------------------------------------------
FILES += [
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/CR conseil ecole 2022-10-12.pdf", "2022-10-15"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/CR conseil ecole 2022-10-12 - Copie.pdf", "2022-10-15"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/CR_2023-03-21.pdf", "2023-03-24"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/règlement intérieur école.pdf", "2018-09-10"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/reglement interieur ecole 2022.pdf", "2022-09-08"),
    # Casse incohérente : ECOLE en majuscules
    ("Conseils d'ecole/ECOLE Marie Curie/CR ce nov 2023.docx", "2023-11-21"),
    ("Conseils d'ecole/ECOLE Marie Curie/CR ce nov 2023 V2.docx", "2023-11-22"),
    ("Conseils d'ecole/ECOLE Marie Curie/CR ce nov 2023 VF.docx", "2023-11-23"),
]


# ---------------------------------------------------------------------------
# RESTAURATION/  — marché, factures, menus, PAI nominatif, versions
# ---------------------------------------------------------------------------
FILES += [
    ("RESTAURATION/Marchés publics/2023_renouvellement/CCTP cantine.docx", "2023-03-10"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/CCTP cantine VF.docx", "2023-03-22"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/PV ouverture plis.pdf", "2023-06-03"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/notification attributaire.pdf", "2023-07-15"),
    ("RESTAURATION/Factures/factures cantine 2022.xlsx", "2022-12-29"),
    ("RESTAURATION/Factures/factures_cantine_2023.xlsx", "2023-12-30"),
    ("RESTAURATION/Factures/kermesse_2023_001.jpg", "2023-06-24"),  # mauvais classement
    ("RESTAURATION/Menus/menu sept-dec 2023.pdf", "2023-08-30"),
    ("RESTAURATION/Allergies PAI/PAI Lucas DURAND signe.pdf", "2022-09-15"),
    ("RESTAURATION/Allergies PAI/liste PAI 2023-2024.xlsx", "2023-09-20"),
    ("RESTAURATION/Reglement cantine v1.docx", "2018-08-20"),
    ("RESTAURATION/Reglement cantine VF.docx", "2020-08-24"),
    ("RESTAURATION/Reglement cantine FINAL_VRAI.docx", "2021-08-30"),
]


# ---------------------------------------------------------------------------
# Transport scolaire 2020-2024/  — fichiers en vrac
# ---------------------------------------------------------------------------
FILES += [
    ("Transport scolaire 2020-2024/circuit bus 2022-2023.pdf", "2022-08-19"),
    ("Transport scolaire 2020-2024/CIRCUIT BUS 2023-2024.pdf", "2023-08-21"),
    ("Transport scolaire 2020-2024/convention transport CD 2024.pdf", "2024-06-28"),
    ("Transport scolaire 2020-2024/liste enfants transport 2023.xlsx", "2023-09-04"),
    ("Transport scolaire 2020-2024/RE_ retard bus matin.msg", "2023-11-08"),
]


# ---------------------------------------------------------------------------
# Periscolaire ALSH garderie/  — sous-dossier ALSH organisé, garderie en vrac
# ---------------------------------------------------------------------------
FILES += [
    ("Periscolaire ALSH garderie/ALSH/projet pédagogique 2023-2024.pdf", "2023-09-03"),
    ("Periscolaire ALSH garderie/ALSH/inscriptions ALSH 2023-2024.xlsx", "2023-09-08"),
    ("Periscolaire ALSH garderie/ALSH/planning vacances fevrier 2024.xlsx", "2024-01-22"),
    ("Periscolaire ALSH garderie/garderie inscriptions 2023-2024.xlsx", "2023-09-08"),
    ("Periscolaire ALSH garderie/règlement garderie.pdf", "2019-08-29"),
    ("Periscolaire ALSH garderie/reglement garderie 2023.pdf", "2023-08-29"),
    ("Periscolaire ALSH garderie/tarifs periscolaire 2024.pdf", "2024-06-30"),
    ("Periscolaire ALSH garderie/test.pdf", "2022-04-11"),
]


# ---------------------------------------------------------------------------
# Travaux ecoles/  — devis, plans, photos
# ---------------------------------------------------------------------------
FILES += [
    ("Travaux ecoles/devis preau Marie Curie 2023.pdf", "2023-05-30"),
    ("Travaux ecoles/devis preau Marie Curie 2023 v2.pdf", "2023-06-12"),
    ("Travaux ecoles/PLANS Jules Ferry niveau RDC.pdf", "2019-02-15"),
    ("Travaux ecoles/IMG_8821.JPG", "2022-04-05"),
    ("Travaux ecoles/IMG_8822.JPG", "2022-04-05"),
    ("Travaux ecoles/DTA ecoles 2022.pdf", "2022-11-14"),
]


# ---------------------------------------------------------------------------
# ATSEM - Personnel/  — données nominatives sensibles
# ---------------------------------------------------------------------------
FILES += [
    ("ATSEM - Personnel/planning ATSEM 2023-2024.xlsx", "2023-08-30"),
    ("ATSEM - Personnel/fiche poste ATSEM 2022.docx", "2022-04-08"),
    ("ATSEM - Personnel/CV Sophie BERNARD candidature.pdf", "2022-06-20"),
    ("ATSEM - Personnel/entretien annuel S_BERNARD 2023.pdf", "2023-11-28"),
    ("ATSEM - Personnel/formation HACCP attestation S_BERNARD.pdf", "2023-10-04"),
]


# ---------------------------------------------------------------------------
# Communication parents/
# ---------------------------------------------------------------------------
FILES += [
    ("Communication parents/courrier rentrée 2023.docx", "2023-08-21"),
    ("Communication parents/affiche kermesse 2023.pptx", "2023-05-30"),
    ("Communication parents/affiche kermesse 2023 VF.pptx", "2023-06-08"),
    ("Communication parents/note info COVID mars 2020.pdf", "2020-03-15"),
    ("Communication parents/RE_ inscription cantine - urgent.msg", "2023-09-04"),
]


# ---------------------------------------------------------------------------
# Photos kermesse fete ecole/  — IMG_xxxx en vrac
# ---------------------------------------------------------------------------
FILES += [
    ("Photos kermesse fete ecole/IMG_2301.JPG", "2019-06-22"),
    ("Photos kermesse fete ecole/IMG_2302.JPG", "2019-06-22"),
    ("Photos kermesse fete ecole/kermesse_2022_001.jpg", "2022-06-25"),
    ("Photos kermesse fete ecole/kermesse_2022_002.jpg", "2022-06-25"),
    ("Photos kermesse fete ecole/Kermesse 2023 - photos officielles/photo_001.png", "2023-06-24"),
    ("Photos kermesse fete ecole/Kermesse 2023 - photos officielles/photo_002.png", "2023-06-24"),
    ("Photos kermesse fete ecole/photos vrac.zip", "2023-06-26"),
]


# ---------------------------------------------------------------------------
# A CLASSER/  — fourre-tout
# ---------------------------------------------------------------------------
FILES += [
    ("A CLASSER/SCAN_0987.pdf", "2023-02-08"),
    ("A CLASSER/document sans nom.pdf", "2023-04-12"),
    ("A CLASSER/truc.docx", "2022-11-03"),
    ("A CLASSER/email export.eml", "2023-11-22"),
    ("A CLASSER/copie_passeport_eleve.pdf", "2022-09-08"),
]


# ---------------------------------------------------------------------------
# OLD/  — auto-archivage maison
# ---------------------------------------------------------------------------
FILES += [
    ("OLD/Sauvegarde poste Christine 2019/mes documents/perso/photo chat.jpg", "2018-12-04"),
    ("OLD/Sauvegarde poste Christine 2019/mes documents/travail/CR conseil ecole 2018-11-08.pdf", "2018-11-12"),
    ("OLD/Sauvegarde poste Christine 2019/Telechargements/installeur acrobat.exe", "2018-07-03"),
    ("OLD/anciens reglements/reglement cantine 2015.pdf", "2015-08-30"),
    ("OLD/anciens reglements/reglement garderie 2014.pdf", "2014-08-29"),
    ("OLD/listes 2017-2018/liste eleves CP 2017.xlsx", "2017-09-05"),
]


# ---------------------------------------------------------------------------
# Nouveau dossier (2)/  — relique
# ---------------------------------------------------------------------------
FILES += [
    ("Nouveau dossier (2)/sans titre.docx", "2022-10-17"),
]


# ---------------------------------------------------------------------------
# Fichiers à la racine du service
# ---------------------------------------------------------------------------
FILES += [
    ("CV_Martine_DUPONT.pdf", "2019-03-14"),
    ("organigramme service 2023.pptx", "2023-01-09"),
    ("Document1.pdf", "2024-02-28"),
]


# Dossiers vides
EMPTY_DIRS: list[str] = [
    "Archives 2018",
    "Nouveau dossier",
]


def main() -> None:
    if TARGET.exists():
        print(f"Suppression de l'arborescence existante : {TARGET}")
        shutil.rmtree(TARGET)

    TARGET.mkdir(parents=True)
    print(f"Création de : {TARGET}")

    for relpath, date_str in FILES:
        full = TARGET / relpath
        full.parent.mkdir(parents=True, exist_ok=True)
        full.touch()

        dt = datetime.fromisoformat(date_str)
        hour = random.randint(8, 17)
        minute = random.randint(0, 59)
        dt = dt.replace(hour=hour, minute=minute)
        ts = dt.timestamp()
        os.utime(full, (ts, ts))

    for empty in EMPTY_DIRS:
        (TARGET / empty).mkdir(parents=True, exist_ok=True)

    n_files = len(FILES)
    n_dirs = sum(1 for _ in TARGET.rglob("*") if _.is_dir())
    print(f"OK — {n_files} fichiers, {n_dirs} dossiers générés.")
    print(f"Racine : {TARGET}")


if __name__ == "__main__":
    main()
