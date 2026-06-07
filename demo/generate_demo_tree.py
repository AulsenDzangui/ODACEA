"""
Génère une arborescence bureautique fictive d'un service municipal pour
démontrer Odile à des archivistes.

Service simulé : Mairie de Saint-Genis-le-Champêtre — Affaires scolaires
                 et périscolaire (sept. 2018 → juin 2024).

Le désordre est volontaire : doublons, versions cumulées, naming scanner,
casse incohérente, dossiers fourre-tout, données personnelles à la racine,
mauvais classements. Chaque fichier porte une mtime cohérente avec son nom
pour produire un audit réaliste dans Odile / Archifiltre.

Usage :
    python scripts/generate_demo_tree.py
"""

from __future__ import annotations

import os
import random
import shutil
from datetime import datetime
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "demo_data" / "Mairie_Saint-Genis_Affaires_Scolaires"


# Liste : (chemin relatif à TARGET, date au format YYYY-MM-DD)
# Chaque ligne est choisie pour illustrer un pattern de désordre précis.
FILES: list[tuple[str, str]] = []


# ---------------------------------------------------------------------------
# 01_Inscriptions scolaires/
# ---------------------------------------------------------------------------
FILES += [
    # Sous-dossier propre par année scolaire
    ("01_Inscriptions scolaires/Inscriptions 2018-2019/Liste eleves CP - 2018.xlsx", "2018-09-03"),
    ("01_Inscriptions scolaires/Inscriptions 2018-2019/Liste eleves CE1 2018.xlsx", "2018-09-03"),
    ("01_Inscriptions scolaires/Inscriptions 2018-2019/Liste_eleves_CE2_2018.xlsx", "2018-09-04"),
    ("01_Inscriptions scolaires/Inscriptions 2018-2019/dossier inscription type.docx", "2018-06-15"),

    ("01_Inscriptions scolaires/Inscriptions 2019-2020/Liste eleves CP 2019.xlsx", "2019-09-02"),
    ("01_Inscriptions scolaires/Inscriptions 2019-2020/Liste eleves CE1 2019.xlsx", "2019-09-02"),
    ("01_Inscriptions scolaires/Inscriptions 2019-2020/derogations 2019.pdf", "2019-08-26"),

    # Naming année civile vs scolaire mélangé pour la même rentrée
    ("01_Inscriptions scolaires/Inscriptions 2022-2023/Liste eleves rentree 2022.xlsx", "2022-09-01"),
    ("01_Inscriptions scolaires/Inscriptions 2022-2023/derogations.pdf", "2022-08-22"),
    ("01_Inscriptions scolaires/Inscriptions 2022-2023/derogations - Copie.pdf", "2022-08-22"),
    ("01_Inscriptions scolaires/Inscriptions 2023/Liste eleves rentree 2022.xlsx", "2022-09-01"),  # mauvais dossier
    ("01_Inscriptions scolaires/Inscriptions 2023/Liste eleves CP rentree 2023.xlsx", "2023-09-04"),

    # Sous-dossier 2024 mal nommé (juste l'année)
    ("01_Inscriptions scolaires/2024/inscriptions rentrée 2024-2025.xlsx", "2024-06-12"),
    ("01_Inscriptions scolaires/2024/courrier parents - rentree 2024.docx", "2024-06-20"),
    ("01_Inscriptions scolaires/2024/courrier parents - rentree 2024 VF.docx", "2024-06-25"),
    ("01_Inscriptions scolaires/2024/courrier parents - rentree 2024 VF_corrigé.docx", "2024-06-26"),
    ("01_Inscriptions scolaires/2024/courrier parents - rentree 2024 FINAL_VRAI.docx", "2024-06-27"),

    # Fichiers à la racine de Inscriptions
    ("01_Inscriptions scolaires/dossier inscription - modele.docx", "2018-05-10"),
    ("01_Inscriptions scolaires/dossier inscription modele 2022.docx", "2022-05-15"),
    ("01_Inscriptions scolaires/SCAN_0034.pdf", "2021-09-12"),
    ("01_Inscriptions scolaires/SCAN_0035.pdf", "2021-09-12"),
    ("01_Inscriptions scolaires/aaaa.pdf", "2020-11-03"),
]


# ---------------------------------------------------------------------------
# Conseils d'ecole/  (3 écoles, casse incohérente, naming irrégulier)
# ---------------------------------------------------------------------------
FILES += [
    # École maternelle Jean Jaurès
    ("Conseils d'ecole/Ecole maternelle Jean Jaures/CR conseil ecole 2019-11-05.pdf", "2019-11-08"),
    ("Conseils d'ecole/Ecole maternelle Jean Jaures/CR conseil ecole 2020-02-10.pdf", "2020-02-14"),
    ("Conseils d'ecole/Ecole maternelle Jean Jaures/Compte rendu CE 2022-10-12.pdf", "2022-10-15"),
    ("Conseils d'ecole/Ecole maternelle Jean Jaures/Compte rendu CE 2022-10-12 - Copie.pdf", "2022-10-15"),
    ("Conseils d'ecole/Ecole maternelle Jean Jaures/CR_CE_2023-03-21.pdf", "2023-03-24"),
    ("Conseils d'ecole/Ecole maternelle Jean Jaures/PV conseil ecole juin 2023.docx", "2023-06-22"),
    ("Conseils d'ecole/Ecole maternelle Jean Jaures/~$ conseil ecole juin 2023.docx", "2023-06-22"),  # temp Office

    # École élémentaire Jules Ferry
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/CR conseil ecole 2019-11-12.pdf", "2019-11-15"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/CR conseil ecole 2020-11-10.pdf", "2020-11-13"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/CR conseil ecole 2021-03-09.pdf", "2021-03-12"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/CR_2022_06_28.pdf", "2022-06-30"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/Compte rendu conseil ecole 2023-11-14.docx", "2023-11-17"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/Document1.pdf", "2024-03-15"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/règlement intérieur école.pdf", "2018-09-10"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/reglement interieur ecole 2022.pdf", "2022-09-08"),

    # École Marie Curie — casse incohérente
    ("Conseils d'ecole/ECOLE Marie Curie/CR conseil ecole 2020-02-04.pdf", "2020-02-07"),
    ("Conseils d'ecole/ECOLE Marie Curie/CR conseil ecole 2021-11-16.pdf", "2021-11-19"),
    ("Conseils d'ecole/ECOLE Marie Curie/Compte rendu CE marie curie 2023.pdf", "2023-03-10"),
    ("Conseils d'ecole/ECOLE Marie Curie/CR ce nov 2023.docx", "2023-11-21"),
    ("Conseils d'ecole/ECOLE Marie Curie/CR ce nov 2023 V2.docx", "2023-11-22"),
    ("Conseils d'ecole/ECOLE Marie Curie/CR ce nov 2023 VF.docx", "2023-11-23"),
]


# ---------------------------------------------------------------------------
# RESTAURATION/
# ---------------------------------------------------------------------------
FILES += [
    # Marchés publics
    ("RESTAURATION/Marchés publics/2019_marche_cantine/cahier des charges.pdf", "2019-04-12"),
    ("RESTAURATION/Marchés publics/2019_marche_cantine/CCTP cantine.pdf", "2019-04-12"),
    ("RESTAURATION/Marchés publics/2019_marche_cantine/PV ouverture plis.pdf", "2019-06-03"),
    ("RESTAURATION/Marchés publics/2019_marche_cantine/notification attributaire.pdf", "2019-07-15"),
    ("RESTAURATION/Marchés publics/2019_marche_cantine/contrat signe scan.pdf", "2019-08-02"),

    ("RESTAURATION/Marchés publics/2023_renouvellement/CCTP cantine 2023.docx", "2023-03-10"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/CCTP cantine v2.docx", "2023-03-15"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/CCTP cantine VF.docx", "2023-03-22"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/CCTP cantine FINAL_VRAI.docx", "2023-03-28"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/offres recues/Sodexo.pdf", "2023-05-12"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/offres recues/Elior.pdf", "2023-05-12"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/offres recues/API restauration.pdf", "2023-05-13"),

    # Factures
    ("RESTAURATION/Factures/factures cantine 2020.xlsx", "2020-12-31"),
    ("RESTAURATION/Factures/factures_cantine_2021.xlsx", "2021-12-30"),
    ("RESTAURATION/Factures/factures cantine 2022.xlsx", "2022-12-29"),
    ("RESTAURATION/Factures/SCAN_0234.pdf", "2022-04-08"),
    ("RESTAURATION/Factures/SCAN_0235.pdf", "2022-04-08"),
    ("RESTAURATION/Factures/kermesse_2023_001.jpg", "2023-06-24"),  # mauvais classement
    ("RESTAURATION/Factures/IMG_4523.JPG", "2022-05-19"),

    # Menus
    ("RESTAURATION/Menus/menu janv-mars 2022.pdf", "2022-01-03"),
    ("RESTAURATION/Menus/menu_avril_juin_2022.pdf", "2022-03-25"),
    ("RESTAURATION/Menus/menu sept-dec 2022.pdf", "2022-08-30"),
    ("RESTAURATION/Menus/menus 2023-2024.xlsx", "2023-08-28"),

    # Allergies / PAI (données nominatives sensibles)
    ("RESTAURATION/Allergies PAI/PAI Lucas DURAND signe.pdf", "2022-09-15"),
    ("RESTAURATION/Allergies PAI/PAI Emma LEROY 2023.pdf", "2023-09-12"),
    ("RESTAURATION/Allergies PAI/liste PAI 2023-2024.xlsx", "2023-09-20"),

    # Règlement cantine — versions cumulées
    ("RESTAURATION/Reglement cantine v1.docx", "2018-08-20"),
    ("RESTAURATION/Reglement cantine v2.docx", "2019-08-22"),
    ("RESTAURATION/Reglement cantine VF.docx", "2020-08-24"),
    ("RESTAURATION/Reglement cantine VF_corrigé.docx", "2020-09-01"),
    ("RESTAURATION/Reglement cantine FINAL_VRAI.docx", "2021-08-30"),
]


# ---------------------------------------------------------------------------
# Transport scolaire 2020-2024/  (tout en vrac, pas de sous-dossiers)
# ---------------------------------------------------------------------------
FILES += [
    ("Transport scolaire 2020-2024/circuit bus 2020-2021.pdf", "2020-08-15"),
    ("Transport scolaire 2020-2024/circuit bus 2021-2022.pdf", "2021-08-18"),
    ("Transport scolaire 2020-2024/circuit bus 2022-2023.pdf", "2022-08-19"),
    ("Transport scolaire 2020-2024/CIRCUIT BUS 2023-2024.pdf", "2023-08-21"),
    ("Transport scolaire 2020-2024/convention transport CD 2020.pdf", "2020-07-04"),
    ("Transport scolaire 2020-2024/convention transport CD 2024.pdf", "2024-06-28"),
    ("Transport scolaire 2020-2024/liste enfants transport 2022.xlsx", "2022-09-05"),
    ("Transport scolaire 2020-2024/liste_enfants_transport_2023.xlsx", "2023-09-04"),
    ("Transport scolaire 2020-2024/incidents bus.docx", "2023-02-14"),
    ("Transport scolaire 2020-2024/RE_ retard bus matin.msg", "2023-11-08"),
]


# ---------------------------------------------------------------------------
# Periscolaire ALSH garderie/  (sous-dossier ALSH propre, garderie en vrac)
# ---------------------------------------------------------------------------
FILES += [
    # ALSH (sous-dossier organisé)
    ("Periscolaire ALSH garderie/ALSH/projet pedagogique 2021-2022.pdf", "2021-09-01"),
    ("Periscolaire ALSH garderie/ALSH/projet pedagogique 2022-2023.pdf", "2022-09-02"),
    ("Periscolaire ALSH garderie/ALSH/projet pédagogique 2023-2024.pdf", "2023-09-03"),
    ("Periscolaire ALSH garderie/ALSH/agrement DDCS 2020.pdf", "2020-06-12"),
    ("Periscolaire ALSH garderie/ALSH/agrement DDCS 2023.pdf", "2023-06-14"),
    ("Periscolaire ALSH garderie/ALSH/planning vacances toussaint 2023.xlsx", "2023-09-25"),
    ("Periscolaire ALSH garderie/ALSH/planning vacances fevrier 2024.xlsx", "2024-01-22"),
    ("Periscolaire ALSH garderie/ALSH/inscriptions ALSH 2023-2024.xlsx", "2023-09-08"),

    # Garderie — pas de sous-dossier, fichiers en vrac
    ("Periscolaire ALSH garderie/garderie matin liste 2022.xlsx", "2022-09-06"),
    ("Periscolaire ALSH garderie/garderie soir liste 2022.xlsx", "2022-09-06"),
    ("Periscolaire ALSH garderie/garderie inscriptions 2023-2024.xlsx", "2023-09-08"),
    ("Periscolaire ALSH garderie/règlement garderie.pdf", "2019-08-29"),
    ("Periscolaire ALSH garderie/reglement garderie 2023.pdf", "2023-08-29"),
    ("Periscolaire ALSH garderie/tarifs periscolaire 2022.pdf", "2022-08-25"),
    ("Periscolaire ALSH garderie/tarifs periscolaire 2023.pdf", "2023-08-26"),
    ("Periscolaire ALSH garderie/tarifs periscolaire 2024.pdf", "2024-06-30"),

    # Photos et fichiers mal classés
    ("Periscolaire ALSH garderie/photo sortie ALSH ete 2023.jpg", "2023-07-20"),
    ("Periscolaire ALSH garderie/photo sortie ALSH ete 2023 (2).jpg", "2023-07-20"),
    ("Periscolaire ALSH garderie/test.pdf", "2022-04-11"),
]


# ---------------------------------------------------------------------------
# Travaux ecoles/  (devis, plans, photos en vrac)
# ---------------------------------------------------------------------------
FILES += [
    ("Travaux ecoles/devis ravalement Jules Ferry 2020.pdf", "2020-03-18"),
    ("Travaux ecoles/devis ravalement Jules Ferry 2020 - Copie.pdf", "2020-03-18"),
    ("Travaux ecoles/devis chaufferie maternelle 2021.pdf", "2021-04-22"),
    ("Travaux ecoles/plan ecole maternelle Jaures.pdf", "2018-05-10"),
    ("Travaux ecoles/PLANS Jules Ferry niveau RDC.pdf", "2019-02-15"),
    ("Travaux ecoles/PLANS Jules Ferry niveau R+1.pdf", "2019-02-15"),
    ("Travaux ecoles/photo cour ecole 2022 avant.jpg", "2022-04-05"),
    ("Travaux ecoles/photo cour ecole 2022 apres.jpg", "2022-08-29"),
    ("Travaux ecoles/IMG_8821.JPG", "2022-04-05"),
    ("Travaux ecoles/IMG_8822.JPG", "2022-04-05"),
    ("Travaux ecoles/IMG_8823.JPG", "2022-04-05"),
    ("Travaux ecoles/devis preau Marie Curie 2023.pdf", "2023-05-30"),
    ("Travaux ecoles/devis preau Marie Curie 2023 v2.pdf", "2023-06-12"),
    ("Travaux ecoles/note technique amiante 2019.pdf", "2019-10-08"),
    ("Travaux ecoles/DTA ecoles 2022.pdf", "2022-11-14"),
]


# ---------------------------------------------------------------------------
# ATSEM - Personnel/  (données nominatives sensibles)
# ---------------------------------------------------------------------------
FILES += [
    ("ATSEM - Personnel/planning ATSEM 2022-2023.xlsx", "2022-08-30"),
    ("ATSEM - Personnel/planning ATSEM 2023-2024.xlsx", "2023-08-30"),
    ("ATSEM - Personnel/fiche poste ATSEM.docx", "2018-05-04"),
    ("ATSEM - Personnel/fiche poste ATSEM 2022.docx", "2022-04-08"),
    ("ATSEM - Personnel/CV Martine DUPONT.pdf", "2019-03-14"),
    ("ATSEM - Personnel/CV Sophie BERNARD candidature.pdf", "2022-06-20"),
    ("ATSEM - Personnel/entretien annuel M_DUPONT 2022.pdf", "2022-11-25"),
    ("ATSEM - Personnel/entretien annuel S_BERNARD 2023.pdf", "2023-11-28"),
    ("ATSEM - Personnel/arret maladie M_DUPONT mars 2023.pdf", "2023-03-12"),
    ("ATSEM - Personnel/formation HACCP attestation S_BERNARD.pdf", "2023-10-04"),
]


# ---------------------------------------------------------------------------
# Communication parents/
# ---------------------------------------------------------------------------
FILES += [
    ("Communication parents/courrier rentree type.docx", "2018-08-12"),
    ("Communication parents/courrier rentrée 2022.docx", "2022-08-22"),
    ("Communication parents/courrier rentrée 2023.docx", "2023-08-21"),
    ("Communication parents/mailing parents inscriptions 2023.docx", "2023-05-15"),
    ("Communication parents/affiche kermesse 2023.pptx", "2023-05-30"),
    ("Communication parents/affiche kermesse 2023 v2.pptx", "2023-06-02"),
    ("Communication parents/affiche kermesse 2023 VF.pptx", "2023-06-08"),
    ("Communication parents/note info COVID mars 2020.pdf", "2020-03-15"),
    ("Communication parents/note info COVID sept 2020.pdf", "2020-08-31"),
    ("Communication parents/RE_ inscription cantine - urgent.msg", "2023-09-04"),
]


# ---------------------------------------------------------------------------
# Photos kermesse fete ecole/  (IMG_xxxx en vrac)
# ---------------------------------------------------------------------------
FILES += [
    ("Photos kermesse fete ecole/IMG_2301.JPG", "2019-06-22"),
    ("Photos kermesse fete ecole/IMG_2302.JPG", "2019-06-22"),
    ("Photos kermesse fete ecole/IMG_2303.JPG", "2019-06-22"),
    ("Photos kermesse fete ecole/IMG_2304.JPG", "2019-06-22"),
    ("Photos kermesse fete ecole/IMG_2305.JPG", "2019-06-22"),
    ("Photos kermesse fete ecole/kermesse_2022_001.jpg", "2022-06-25"),
    ("Photos kermesse fete ecole/kermesse_2022_002.jpg", "2022-06-25"),
    ("Photos kermesse fete ecole/kermesse_2022_003.jpg", "2022-06-25"),
    ("Photos kermesse fete ecole/kermesse_2022_004.jpg", "2022-06-25"),
    ("Photos kermesse fete ecole/Kermesse 2023 - photos officielles/photo_001.png", "2023-06-24"),
    ("Photos kermesse fete ecole/Kermesse 2023 - photos officielles/photo_002.png", "2023-06-24"),
    ("Photos kermesse fete ecole/Kermesse 2023 - photos officielles/photo_003.png", "2023-06-24"),
    ("Photos kermesse fete ecole/Kermesse 2023 - photos officielles/photo_004.png", "2023-06-24"),
    ("Photos kermesse fete ecole/photos vrac.zip", "2023-06-26"),
    ("Photos kermesse fete ecole/DSC00021.JPG", "2018-06-23"),
    ("Photos kermesse fete ecole/DSC00022.JPG", "2018-06-23"),
    ("Photos kermesse fete ecole/photo classe CP 2021.jpg", "2021-06-18"),
    ("Photos kermesse fete ecole/photo classe CE2 2021.jpg", "2021-06-18"),
]


# ---------------------------------------------------------------------------
# A CLASSER/  (fourre-tout typique)
# ---------------------------------------------------------------------------
FILES += [
    ("A CLASSER/scan recu mairie 2022.pdf", "2022-04-19"),
    ("A CLASSER/SCAN_0987.pdf", "2023-02-08"),
    ("A CLASSER/document sans nom.pdf", "2023-04-12"),
    ("A CLASSER/truc.docx", "2022-11-03"),
    ("A CLASSER/note manuscrite scan.pdf", "2023-09-15"),
    ("A CLASSER/photo non identifiee.jpg", "2022-07-04"),
    ("A CLASSER/email export.eml", "2023-11-22"),
    ("A CLASSER/Document1.pdf", "2024-01-10"),
    ("A CLASSER/Document2.pdf", "2024-01-10"),
    ("A CLASSER/copie_passeport_eleve.pdf", "2022-09-08"),
]


# ---------------------------------------------------------------------------
# OLD/  (auto-archivage maison, dump complet d'un poste)
# ---------------------------------------------------------------------------
FILES += [
    ("OLD/Sauvegarde poste Christine 2019/mes documents/perso/photo chat.jpg", "2018-12-04"),
    ("OLD/Sauvegarde poste Christine 2019/mes documents/perso/recettes.docx", "2019-02-11"),
    ("OLD/Sauvegarde poste Christine 2019/mes documents/travail/CR conseil ecole 2018-11-08.pdf", "2018-11-12"),
    ("OLD/Sauvegarde poste Christine 2019/mes documents/travail/menus 2018.pdf", "2018-09-04"),
    ("OLD/Sauvegarde poste Christine 2019/Bureau/raccourcis/note rapide.txt", "2019-05-22"),
    ("OLD/Sauvegarde poste Christine 2019/Telechargements/facture orange janv2019.pdf", "2019-01-15"),
    ("OLD/Sauvegarde poste Christine 2019/Telechargements/installeur acrobat.exe", "2018-07-03"),
    ("OLD/anciens reglements/reglement cantine 2015.pdf", "2015-08-30"),
    ("OLD/anciens reglements/reglement garderie 2014.pdf", "2014-08-29"),
    ("OLD/anciens reglements/reglement transport 2016.pdf", "2016-08-31"),
    ("OLD/listes 2017-2018/liste eleves CP 2017.xlsx", "2017-09-05"),
    ("OLD/listes 2017-2018/liste eleves CE1 2017.xlsx", "2017-09-05"),
]


# ---------------------------------------------------------------------------
# Nouveau dossier (2)/  (1 fichier oublié)
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
    ("scan a trier.pdf", "2024-03-04"),
    ("aaaa.pdf", "2023-08-08"),
]


# Dossiers vides à créer en plus (pas de fichiers à l'intérieur)
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

        # mtime + atime cohérentes avec le contenu
        dt = datetime.fromisoformat(date_str)
        # Heure légèrement randomisée (heures de bureau) pour réalisme
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
