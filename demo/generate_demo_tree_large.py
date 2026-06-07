"""
Version étendue (~450 fichiers) de l'arborescence bureautique fictive,
calibrée pour tester l'app sur des grands modèles cloud (Claude Opus,
GPT-4/5, Gemini Pro, fenêtres 200k+).

Reprend l'intégralité de la version moyenne et étend chaque branche :
- toutes les années scolaires 2018-19 → 2024-25 couvertes
- factures et menus mensuels au lieu de trimestriels
- séries IMG_xxxx plus longues (kermesses, sorties)
- plus de conseils d'école, devis, plannings vacances, PAI, entretiens
- dossier OLD plus volumineux

Le dossier généré est distinct des autres tailles pour pouvoir coexister :
    demo_data/Mairie_Saint-Genis_Affaires_Scolaires_LARGE/

Usage :
    python scripts/generate_demo_tree_large.py
"""

from __future__ import annotations

import os
import random
import shutil
from datetime import datetime
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "demo_data" / "Mairie_Saint-Genis_Affaires_Scolaires_LARGE"


FILES: list[tuple[str, str]] = []


# ---------------------------------------------------------------------------
# 01_Inscriptions scolaires/  — toutes les années 2018-19 → 2024-25
# ---------------------------------------------------------------------------
INSCRIPTIONS_YEARS = [
    ("2018-2019", "2018-09-03"),
    ("2019-2020", "2019-09-02"),
    ("2020-2021", "2020-09-01"),
    ("2021-2022", "2021-09-02"),
    ("2022-2023", "2022-09-01"),
    ("2023-2024", "2023-09-04"),
    ("2024-2025", "2024-09-03"),
]
for ystr, date in INSCRIPTIONS_YEARS:
    yshort = ystr.split("-")[0]
    base = f"01_Inscriptions scolaires/Inscriptions {ystr}"
    FILES += [
        (f"{base}/Liste eleves CP {yshort}.xlsx", date),
        (f"{base}/Liste eleves CE1 {yshort}.xlsx", date),
        (f"{base}/Liste eleves CE2 {yshort}.xlsx", date),
        (f"{base}/Liste eleves CM1 {yshort}.xlsx", date),
        (f"{base}/Liste eleves CM2 {yshort}.xlsx", date),
        (f"{base}/derogations {yshort}.pdf", f"{yshort}-08-22"),
        (f"{base}/courrier rentree {yshort}.docx", f"{yshort}-08-25"),
    ]
# Doublons et désordre
FILES += [
    ("01_Inscriptions scolaires/Inscriptions 2022-2023/derogations - Copie.pdf", "2022-08-22"),
    ("01_Inscriptions scolaires/Inscriptions 2022-2023/derogations - Copie (2).pdf", "2022-08-22"),
    ("01_Inscriptions scolaires/Inscriptions 2023/Liste eleves rentree 2022.xlsx", "2022-09-01"),  # mauvais dossier
    ("01_Inscriptions scolaires/Inscriptions 2023/Liste eleves CP rentree 2023.xlsx", "2023-09-04"),
    ("01_Inscriptions scolaires/2024/inscriptions rentrée 2024-2025.xlsx", "2024-06-12"),
    ("01_Inscriptions scolaires/2024/courrier parents - rentree 2024.docx", "2024-06-20"),
    ("01_Inscriptions scolaires/2024/courrier parents - rentree 2024 VF.docx", "2024-06-25"),
    ("01_Inscriptions scolaires/2024/courrier parents - rentree 2024 VF_corrigé.docx", "2024-06-26"),
    ("01_Inscriptions scolaires/2024/courrier parents - rentree 2024 FINAL_VRAI.docx", "2024-06-27"),
    ("01_Inscriptions scolaires/dossier inscription - modele.docx", "2018-05-10"),
    ("01_Inscriptions scolaires/dossier inscription modele 2022.docx", "2022-05-15"),
    ("01_Inscriptions scolaires/dossier inscription modele 2024.docx", "2024-05-15"),
    ("01_Inscriptions scolaires/SCAN_0034.pdf", "2021-09-12"),
    ("01_Inscriptions scolaires/SCAN_0035.pdf", "2021-09-12"),
    ("01_Inscriptions scolaires/SCAN_0036.pdf", "2021-09-12"),
    ("01_Inscriptions scolaires/aaaa.pdf", "2020-11-03"),
]


# ---------------------------------------------------------------------------
# Conseils d'ecole/  — 3 écoles × 7 années × 3 conseils par an
# ---------------------------------------------------------------------------
ECOLES = [
    ("Ecole maternelle Jean Jaures", "Jaures"),
    ("Ecole elementaire Jules Ferry", "Ferry"),
    ("ECOLE Marie Curie", "Curie"),  # casse incohérente exprès
]
CONSEILS_DATES = [  # (année scolaire, 3 dates par an)
    ("2018-2019", ["2018-11-08", "2019-02-14", "2019-06-20"]),
    ("2019-2020", ["2019-11-08", "2020-02-14", "2020-06-22"]),
    ("2020-2021", ["2020-11-10", "2021-03-09", "2021-06-21"]),
    ("2021-2022", ["2021-11-09", "2022-02-15", "2022-06-28"]),
    ("2022-2023", ["2022-10-12", "2023-03-21", "2023-06-22"]),
    ("2023-2024", ["2023-11-14", "2024-02-13", "2024-06-25"]),
]
for ecole_dir, _ in ECOLES:
    for _, dates in CONSEILS_DATES:
        for d in dates:
            FILES.append((f"Conseils d'ecole/{ecole_dir}/CR conseil ecole {d}.pdf", d))
# Variations / doublons / temp Office
FILES += [
    ("Conseils d'ecole/Ecole maternelle Jean Jaures/Compte rendu CE 2022-10-12 - Copie.pdf", "2022-10-15"),
    ("Conseils d'ecole/Ecole maternelle Jean Jaures/PV conseil ecole juin 2023.docx", "2023-06-22"),
    ("Conseils d'ecole/Ecole maternelle Jean Jaures/~$ conseil ecole juin 2023.docx", "2023-06-22"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/CR_2022_06_28.pdf", "2022-06-30"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/Compte rendu conseil ecole 2023-11-14.docx", "2023-11-17"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/Document1.pdf", "2024-03-15"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/règlement intérieur école.pdf", "2018-09-10"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/reglement interieur ecole 2022.pdf", "2022-09-08"),
    ("Conseils d'ecole/Ecole elementaire Jules Ferry/reglement interieur ecole 2024.pdf", "2024-09-08"),
    ("Conseils d'ecole/ECOLE Marie Curie/Compte rendu CE marie curie 2023.pdf", "2023-03-10"),
    ("Conseils d'ecole/ECOLE Marie Curie/CR ce nov 2023.docx", "2023-11-21"),
    ("Conseils d'ecole/ECOLE Marie Curie/CR ce nov 2023 V2.docx", "2023-11-22"),
    ("Conseils d'ecole/ECOLE Marie Curie/CR ce nov 2023 VF.docx", "2023-11-23"),
]


# ---------------------------------------------------------------------------
# RESTAURATION/  — marchés, factures mensuelles, menus mensuels, PAI, règlement
# ---------------------------------------------------------------------------
FILES += [
    # Marchés publics 2019
    ("RESTAURATION/Marchés publics/2019_marche_cantine/cahier des charges.pdf", "2019-04-12"),
    ("RESTAURATION/Marchés publics/2019_marche_cantine/CCTP cantine.pdf", "2019-04-12"),
    ("RESTAURATION/Marchés publics/2019_marche_cantine/RC cantine.pdf", "2019-04-12"),
    ("RESTAURATION/Marchés publics/2019_marche_cantine/PV ouverture plis.pdf", "2019-06-03"),
    ("RESTAURATION/Marchés publics/2019_marche_cantine/notification attributaire.pdf", "2019-07-15"),
    ("RESTAURATION/Marchés publics/2019_marche_cantine/contrat signe scan.pdf", "2019-08-02"),
    # Marché 2023
    ("RESTAURATION/Marchés publics/2023_renouvellement/CCTP cantine 2023.docx", "2023-03-10"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/CCTP cantine v2.docx", "2023-03-15"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/CCTP cantine VF.docx", "2023-03-22"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/CCTP cantine FINAL_VRAI.docx", "2023-03-28"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/RC 2023.pdf", "2023-03-22"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/AAPC publication BOAMP.pdf", "2023-04-05"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/offres recues/Sodexo.pdf", "2023-05-12"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/offres recues/Elior.pdf", "2023-05-12"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/offres recues/API restauration.pdf", "2023-05-13"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/offres recues/Compass.pdf", "2023-05-13"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/PV CAO.pdf", "2023-06-15"),
    ("RESTAURATION/Marchés publics/2023_renouvellement/notification.pdf", "2023-07-20"),
]
# Factures mensuelles 2020-2024
MONTHS = ["janv", "fev", "mars", "avril", "mai", "juin",
          "juil", "aout", "sept", "oct", "nov", "dec"]
for year in range(2020, 2025):
    for i, m in enumerate(MONTHS, start=1):
        # On saute juillet-août (vacances scolaires) pour réalisme
        if m in ("juil", "aout"):
            continue
        FILES.append((
            f"RESTAURATION/Factures/{year}/facture cantine {m} {year}.pdf",
            f"{year}-{i:02d}-15",
        ))
# SCAN/IMG mal classés en factures
FILES += [
    ("RESTAURATION/Factures/SCAN_0234.pdf", "2022-04-08"),
    ("RESTAURATION/Factures/SCAN_0235.pdf", "2022-04-08"),
    ("RESTAURATION/Factures/SCAN_0236.pdf", "2022-04-08"),
    ("RESTAURATION/Factures/kermesse_2023_001.jpg", "2023-06-24"),  # mauvais classement
    ("RESTAURATION/Factures/IMG_4523.JPG", "2022-05-19"),
    ("RESTAURATION/Factures/recapitulatif annuel 2022.xlsx", "2022-12-31"),
    ("RESTAURATION/Factures/recapitulatif annuel 2023.xlsx", "2023-12-31"),
    ("RESTAURATION/Factures/recapitulatif annuel 2024.xlsx", "2024-12-31"),
]
# Menus mensuels 2021-2024
for year in range(2021, 2025):
    for i, m in enumerate(MONTHS, start=1):
        if m in ("juil", "aout"):
            continue
        FILES.append((
            f"RESTAURATION/Menus/{year}/menu {m} {year}.pdf",
            f"{year}-{i:02d}-01",
        ))
FILES += [
    ("RESTAURATION/Menus/menus 2023-2024.xlsx", "2023-08-28"),
    ("RESTAURATION/Menus/menus 2024-2025.xlsx", "2024-08-28"),
    ("RESTAURATION/Menus/grille mensuelle type.xlsx", "2018-08-30"),
]
# Allergies / PAI nominatifs
PAI_ENFANTS = [
    ("Lucas DURAND", "2022-09-15"),
    ("Emma LEROY", "2023-09-12"),
    ("Hugo MARTIN", "2022-09-20"),
    ("Lina BERNARD", "2023-09-18"),
    ("Nathan PETIT", "2024-09-09"),
    ("Sarah MOREAU", "2021-09-14"),
    ("Theo ROBERT", "2024-09-11"),
]
for nom, date in PAI_ENFANTS:
    FILES.append((f"RESTAURATION/Allergies PAI/PAI {nom} signe.pdf", date))
FILES += [
    ("RESTAURATION/Allergies PAI/liste PAI 2022-2023.xlsx", "2022-09-20"),
    ("RESTAURATION/Allergies PAI/liste PAI 2023-2024.xlsx", "2023-09-20"),
    ("RESTAURATION/Allergies PAI/liste PAI 2024-2025.xlsx", "2024-09-20"),
    ("RESTAURATION/Allergies PAI/protocole allergies type.docx", "2018-08-30"),
    # Versions cumulées du règlement
    ("RESTAURATION/Reglement cantine v1.docx", "2018-08-20"),
    ("RESTAURATION/Reglement cantine v2.docx", "2019-08-22"),
    ("RESTAURATION/Reglement cantine VF.docx", "2020-08-24"),
    ("RESTAURATION/Reglement cantine VF_corrigé.docx", "2020-09-01"),
    ("RESTAURATION/Reglement cantine FINAL_VRAI.docx", "2021-08-30"),
    ("RESTAURATION/Reglement cantine 2023.docx", "2023-08-25"),
    ("RESTAURATION/Reglement cantine 2024.docx", "2024-08-26"),
]


# ---------------------------------------------------------------------------
# Transport scolaire 2018-2024/  (années étendues)
# ---------------------------------------------------------------------------
for year in range(2018, 2025):
    FILES.append((
        f"Transport scolaire 2020-2024/circuit bus {year}-{year+1}.pdf",
        f"{year}-08-{random.randint(15, 28)}",
    ))
    FILES.append((
        f"Transport scolaire 2020-2024/liste enfants transport {year}.xlsx",
        f"{year}-09-04",
    ))
FILES += [
    ("Transport scolaire 2020-2024/CIRCUIT BUS 2023-2024.pdf", "2023-08-21"),  # casse
    ("Transport scolaire 2020-2024/convention transport CD 2018.pdf", "2018-07-04"),
    ("Transport scolaire 2020-2024/convention transport CD 2020.pdf", "2020-07-04"),
    ("Transport scolaire 2020-2024/convention transport CD 2024.pdf", "2024-06-28"),
    ("Transport scolaire 2020-2024/avenant convention 2022.pdf", "2022-09-15"),
    ("Transport scolaire 2020-2024/incidents bus.docx", "2023-02-14"),
    ("Transport scolaire 2020-2024/incidents bus 2024.docx", "2024-03-22"),
    ("Transport scolaire 2020-2024/RE_ retard bus matin.msg", "2023-11-08"),
    ("Transport scolaire 2020-2024/RE_ probleme transport.msg", "2024-02-08"),
    ("Transport scolaire 2020-2024/RE_ accident bus 2024.msg", "2024-04-12"),
    ("Transport scolaire 2020-2024/factures transporteur 2022.xlsx", "2022-12-30"),
    ("Transport scolaire 2020-2024/factures transporteur 2023.xlsx", "2023-12-30"),
    ("Transport scolaire 2020-2024/factures transporteur 2024.xlsx", "2024-12-30"),
]


# ---------------------------------------------------------------------------
# Periscolaire ALSH garderie/  — plannings vacances, projets pédagogiques
# ---------------------------------------------------------------------------
VACANCES = ["toussaint", "noel", "fevrier", "paques", "ete"]
for year in range(2020, 2025):
    for v in VACANCES:
        FILES.append((
            f"Periscolaire ALSH garderie/ALSH/plannings vacances/planning {v} {year}.xlsx",
            f"{year}-01-15",
        ))
for year in range(2018, 2025):
    FILES.append((
        f"Periscolaire ALSH garderie/ALSH/projet pedagogique {year}-{year+1}.pdf",
        f"{year}-09-01",
    ))
FILES += [
    ("Periscolaire ALSH garderie/ALSH/agrement DDCS 2020.pdf", "2020-06-12"),
    ("Periscolaire ALSH garderie/ALSH/agrement DDCS 2023.pdf", "2023-06-14"),
    ("Periscolaire ALSH garderie/ALSH/inscriptions ALSH 2022-2023.xlsx", "2022-09-08"),
    ("Periscolaire ALSH garderie/ALSH/inscriptions ALSH 2023-2024.xlsx", "2023-09-08"),
    ("Periscolaire ALSH garderie/ALSH/inscriptions ALSH 2024-2025.xlsx", "2024-09-08"),
    ("Periscolaire ALSH garderie/ALSH/bilan financier 2022.xlsx", "2022-12-30"),
    ("Periscolaire ALSH garderie/ALSH/bilan financier 2023.xlsx", "2023-12-30"),
    # Garderie en vrac
    ("Periscolaire ALSH garderie/garderie matin liste 2022.xlsx", "2022-09-06"),
    ("Periscolaire ALSH garderie/garderie soir liste 2022.xlsx", "2022-09-06"),
    ("Periscolaire ALSH garderie/garderie matin liste 2023.xlsx", "2023-09-06"),
    ("Periscolaire ALSH garderie/garderie soir liste 2023.xlsx", "2023-09-06"),
    ("Periscolaire ALSH garderie/garderie inscriptions 2023-2024.xlsx", "2023-09-08"),
    ("Periscolaire ALSH garderie/garderie inscriptions 2024-2025.xlsx", "2024-09-08"),
    ("Periscolaire ALSH garderie/règlement garderie.pdf", "2019-08-29"),
    ("Periscolaire ALSH garderie/reglement garderie 2023.pdf", "2023-08-29"),
    ("Periscolaire ALSH garderie/tarifs periscolaire 2022.pdf", "2022-08-25"),
    ("Periscolaire ALSH garderie/tarifs periscolaire 2023.pdf", "2023-08-26"),
    ("Periscolaire ALSH garderie/tarifs periscolaire 2024.pdf", "2024-06-30"),
    ("Periscolaire ALSH garderie/tarifs periscolaire 2025.pdf", "2025-06-30"),
    ("Periscolaire ALSH garderie/photo sortie ALSH ete 2023.jpg", "2023-07-20"),
    ("Periscolaire ALSH garderie/photo sortie ALSH ete 2023 (2).jpg", "2023-07-20"),
    ("Periscolaire ALSH garderie/photo sortie ALSH ete 2023 (3).jpg", "2023-07-20"),
    ("Periscolaire ALSH garderie/test.pdf", "2022-04-11"),
]


# ---------------------------------------------------------------------------
# Travaux ecoles/  — devis, plans, photos, suivi de chantier par école/année
# ---------------------------------------------------------------------------
TRAVAUX_CHANTIERS = [
    ("ravalement Jules Ferry", "2020-03"),
    ("chaufferie maternelle", "2021-04"),
    ("preau Marie Curie", "2023-05"),
    ("toiture Jules Ferry", "2024-06"),
    ("renovation sanitaires Jaures", "2022-07"),
    ("eclairage cour Marie Curie", "2024-09"),
]
for chantier, ym in TRAVAUX_CHANTIERS:
    y, m = ym.split("-")
    FILES += [
        (f"Travaux ecoles/{chantier} {y}/devis initial.pdf", f"{y}-{m}-12"),
        (f"Travaux ecoles/{chantier} {y}/devis revise.pdf", f"{y}-{m}-25"),
        (f"Travaux ecoles/{chantier} {y}/bon de commande.pdf", f"{y}-{int(m):02d}-28"),
        (f"Travaux ecoles/{chantier} {y}/PV reception.pdf", f"{y}-{(int(m)+2):02d}-15"),
    ]
FILES += [
    ("Travaux ecoles/devis ravalement Jules Ferry 2020 - Copie.pdf", "2020-03-18"),
    ("Travaux ecoles/plan ecole maternelle Jaures.pdf", "2018-05-10"),
    ("Travaux ecoles/PLANS Jules Ferry niveau RDC.pdf", "2019-02-15"),
    ("Travaux ecoles/PLANS Jules Ferry niveau R+1.pdf", "2019-02-15"),
    ("Travaux ecoles/PLANS Marie Curie niveau RDC.pdf", "2019-02-15"),
    ("Travaux ecoles/photo cour ecole 2022 avant.jpg", "2022-04-05"),
    ("Travaux ecoles/photo cour ecole 2022 apres.jpg", "2022-08-29"),
    ("Travaux ecoles/note technique amiante 2019.pdf", "2019-10-08"),
    ("Travaux ecoles/DTA ecoles 2022.pdf", "2022-11-14"),
    ("Travaux ecoles/DTA ecoles 2024 mise a jour.pdf", "2024-11-14"),
    ("Travaux ecoles/diagnostic accessibilite 2020.pdf", "2020-04-22"),
    ("Travaux ecoles/Ad'AP 2021-2024.pdf", "2021-01-15"),
]
# Photos chantier en vrac
for n in range(8821, 8835):
    FILES.append((f"Travaux ecoles/IMG_{n}.JPG", "2022-04-05"))


# ---------------------------------------------------------------------------
# ATSEM - Personnel/  — plus d'agents, plus d'années
# ---------------------------------------------------------------------------
ATSEMS = ["M_DUPONT", "S_BERNARD", "C_MOREAU", "L_LAMBERT"]
for year in range(2019, 2025):
    FILES.append((
        f"ATSEM - Personnel/planning ATSEM {year}-{year+1}.xlsx",
        f"{year}-08-30",
    ))
    for atsem in ATSEMS:
        FILES.append((
            f"ATSEM - Personnel/entretiens annuels/{year}/entretien annuel {atsem} {year}.pdf",
            f"{year}-11-25",
        ))
FILES += [
    ("ATSEM - Personnel/fiche poste ATSEM.docx", "2018-05-04"),
    ("ATSEM - Personnel/fiche poste ATSEM 2022.docx", "2022-04-08"),
    ("ATSEM - Personnel/fiche poste ATSEM 2024.docx", "2024-04-08"),
    ("ATSEM - Personnel/CV Martine DUPONT.pdf", "2019-03-14"),
    ("ATSEM - Personnel/CV Sophie BERNARD candidature.pdf", "2022-06-20"),
    ("ATSEM - Personnel/CV Camille MOREAU.pdf", "2020-06-15"),
    ("ATSEM - Personnel/CV Laura LAMBERT.pdf", "2023-08-22"),
    ("ATSEM - Personnel/arret maladie M_DUPONT mars 2023.pdf", "2023-03-12"),
    ("ATSEM - Personnel/arret maladie C_MOREAU oct 2022.pdf", "2022-10-08"),
    ("ATSEM - Personnel/formation HACCP attestation S_BERNARD.pdf", "2023-10-04"),
    ("ATSEM - Personnel/formation HACCP attestation L_LAMBERT.pdf", "2024-03-15"),
    ("ATSEM - Personnel/formation premiers secours 2023.pdf", "2023-05-22"),
    ("ATSEM - Personnel/note de service heures supp 2024.pdf", "2024-05-15"),
]


# ---------------------------------------------------------------------------
# Communication parents/
# ---------------------------------------------------------------------------
for year in range(2018, 2025):
    FILES.append((
        f"Communication parents/courrier rentrée {year}.docx",
        f"{year}-08-22",
    ))
FILES += [
    ("Communication parents/courrier rentree type.docx", "2018-08-12"),
    ("Communication parents/mailing parents inscriptions 2022.docx", "2022-05-15"),
    ("Communication parents/mailing parents inscriptions 2023.docx", "2023-05-15"),
    ("Communication parents/mailing parents inscriptions 2024.docx", "2024-05-15"),
    ("Communication parents/affiche kermesse 2022.pptx", "2022-05-30"),
    ("Communication parents/affiche kermesse 2023.pptx", "2023-05-30"),
    ("Communication parents/affiche kermesse 2023 v2.pptx", "2023-06-02"),
    ("Communication parents/affiche kermesse 2023 VF.pptx", "2023-06-08"),
    ("Communication parents/affiche kermesse 2024.pptx", "2024-05-28"),
    ("Communication parents/note info COVID mars 2020.pdf", "2020-03-15"),
    ("Communication parents/note info COVID sept 2020.pdf", "2020-08-31"),
    ("Communication parents/note info COVID janv 2021.pdf", "2021-01-12"),
    ("Communication parents/note info COVID sept 2021.pdf", "2021-08-30"),
    ("Communication parents/protocole sanitaire ecoles 2020.pdf", "2020-05-04"),
    ("Communication parents/protocole sanitaire ecoles 2021.pdf", "2021-08-30"),
    ("Communication parents/RE_ inscription cantine - urgent.msg", "2023-09-04"),
    ("Communication parents/RE_ probleme transport.msg", "2024-02-12"),
    ("Communication parents/RE_ kermesse benevoles.msg", "2024-05-22"),
    ("Communication parents/lettre info trimestrielle T1 2023.pdf", "2023-12-15"),
    ("Communication parents/lettre info trimestrielle T2 2023.pdf", "2023-04-15"),
    ("Communication parents/lettre info trimestrielle T3 2023.pdf", "2023-07-01"),
]


# ---------------------------------------------------------------------------
# Photos kermesse fete ecole/  — séries IMG_xxxx étendues + DSC_xxxx
# ---------------------------------------------------------------------------
# Kermesse 2019 : IMG_2301-2320
for n in range(2301, 2321):
    FILES.append((f"Photos kermesse fete ecole/IMG_{n}.JPG", "2019-06-22"))
# Kermesse 2022 : kermesse_2022_001-008
for n in range(1, 9):
    FILES.append((
        f"Photos kermesse fete ecole/kermesse_2022_{n:03d}.jpg",
        "2022-06-25",
    ))
# Kermesse 2023 : photos officielles
for n in range(1, 11):
    FILES.append((
        f"Photos kermesse fete ecole/Kermesse 2023 - photos officielles/photo_{n:03d}.png",
        "2023-06-24",
    ))
# Kermesse 2024
for n in range(1, 13):
    FILES.append((
        f"Photos kermesse fete ecole/Kermesse 2024/IMG_{5000+n:04d}.JPG",
        "2024-06-22",
    ))
# DSC_xxxx vrac 2018
for n in range(21, 36):
    FILES.append((f"Photos kermesse fete ecole/DSC{n:05d}.JPG", "2018-06-23"))
FILES += [
    ("Photos kermesse fete ecole/photos vrac.zip", "2023-06-26"),
    ("Photos kermesse fete ecole/photos vrac 2024.zip", "2024-06-28"),
    ("Photos kermesse fete ecole/photo classe CP 2021.jpg", "2021-06-18"),
    ("Photos kermesse fete ecole/photo classe CE2 2021.jpg", "2021-06-18"),
    ("Photos kermesse fete ecole/photo classe CM2 2022.jpg", "2022-06-18"),
    ("Photos kermesse fete ecole/photo classe CP 2023.jpg", "2023-06-18"),
]


# ---------------------------------------------------------------------------
# A CLASSER/  — fourre-tout étendu
# ---------------------------------------------------------------------------
FILES += [
    ("A CLASSER/scan recu mairie 2022.pdf", "2022-04-19"),
    ("A CLASSER/SCAN_0987.pdf", "2023-02-08"),
    ("A CLASSER/SCAN_0988.pdf", "2023-02-08"),
    ("A CLASSER/SCAN_1102.pdf", "2024-01-22"),
    ("A CLASSER/document sans nom.pdf", "2023-04-12"),
    ("A CLASSER/document sans nom (2).pdf", "2023-04-12"),
    ("A CLASSER/truc.docx", "2022-11-03"),
    ("A CLASSER/truc 2.docx", "2023-05-19"),
    ("A CLASSER/note manuscrite scan.pdf", "2023-09-15"),
    ("A CLASSER/photo non identifiee.jpg", "2022-07-04"),
    ("A CLASSER/photo non identifiee (2).jpg", "2022-07-04"),
    ("A CLASSER/email export.eml", "2023-11-22"),
    ("A CLASSER/email export (2).eml", "2024-02-08"),
    ("A CLASSER/Document1.pdf", "2024-01-10"),
    ("A CLASSER/Document2.pdf", "2024-01-10"),
    ("A CLASSER/Document3.pdf", "2024-03-15"),
    ("A CLASSER/copie_passeport_eleve.pdf", "2022-09-08"),
    ("A CLASSER/copie_carte_identite.pdf", "2023-04-22"),
    ("A CLASSER/Nouveau Document Microsoft Word.docx", "2023-08-15"),
]


# ---------------------------------------------------------------------------
# OLD/  — auto-archivage volumineux
# ---------------------------------------------------------------------------
FILES += [
    ("OLD/Sauvegarde poste Christine 2019/mes documents/perso/photo chat.jpg", "2018-12-04"),
    ("OLD/Sauvegarde poste Christine 2019/mes documents/perso/photo vacances.jpg", "2018-08-12"),
    ("OLD/Sauvegarde poste Christine 2019/mes documents/perso/recettes.docx", "2019-02-11"),
    ("OLD/Sauvegarde poste Christine 2019/mes documents/perso/liste courses.txt", "2019-04-03"),
    ("OLD/Sauvegarde poste Christine 2019/mes documents/travail/CR conseil ecole 2018-11-08.pdf", "2018-11-12"),
    ("OLD/Sauvegarde poste Christine 2019/mes documents/travail/CR conseil ecole 2018-02-15.pdf", "2018-02-19"),
    ("OLD/Sauvegarde poste Christine 2019/mes documents/travail/menus 2018.pdf", "2018-09-04"),
    ("OLD/Sauvegarde poste Christine 2019/mes documents/travail/listes eleves 2017.xlsx", "2017-09-05"),
    ("OLD/Sauvegarde poste Christine 2019/Bureau/raccourcis/note rapide.txt", "2019-05-22"),
    ("OLD/Sauvegarde poste Christine 2019/Bureau/raccourcis/aide-memoire.txt", "2019-06-15"),
    ("OLD/Sauvegarde poste Christine 2019/Bureau/post-it numerique.txt", "2019-08-30"),
    ("OLD/Sauvegarde poste Christine 2019/Telechargements/facture orange janv2019.pdf", "2019-01-15"),
    ("OLD/Sauvegarde poste Christine 2019/Telechargements/facture EDF mars2019.pdf", "2019-03-15"),
    ("OLD/Sauvegarde poste Christine 2019/Telechargements/installeur acrobat.exe", "2018-07-03"),
    ("OLD/Sauvegarde poste Christine 2019/Telechargements/setup_chrome.exe", "2018-07-03"),
    ("OLD/anciens reglements/reglement cantine 2013.pdf", "2013-08-30"),
    ("OLD/anciens reglements/reglement cantine 2015.pdf", "2015-08-30"),
    ("OLD/anciens reglements/reglement cantine 2017.pdf", "2017-08-30"),
    ("OLD/anciens reglements/reglement garderie 2014.pdf", "2014-08-29"),
    ("OLD/anciens reglements/reglement garderie 2016.pdf", "2016-08-29"),
    ("OLD/anciens reglements/reglement transport 2016.pdf", "2016-08-31"),
    ("OLD/listes 2014-2018/liste eleves CP 2014.xlsx", "2014-09-05"),
    ("OLD/listes 2014-2018/liste eleves CP 2015.xlsx", "2015-09-05"),
    ("OLD/listes 2014-2018/liste eleves CP 2016.xlsx", "2016-09-05"),
    ("OLD/listes 2014-2018/liste eleves CP 2017.xlsx", "2017-09-05"),
    ("OLD/listes 2014-2018/liste eleves CE1 2017.xlsx", "2017-09-05"),
    ("OLD/listes 2014-2018/liste eleves CE2 2017.xlsx", "2017-09-05"),
    ("OLD/conseils ecole avant 2018/CR ce 2014-11-12.pdf", "2014-11-15"),
    ("OLD/conseils ecole avant 2018/CR ce 2015-11-12.pdf", "2015-11-15"),
    ("OLD/conseils ecole avant 2018/CR ce 2016-11-12.pdf", "2016-11-15"),
    ("OLD/conseils ecole avant 2018/CR ce 2017-11-12.pdf", "2017-11-15"),
]


# ---------------------------------------------------------------------------
# Nouveau dossier (2)/ et fichiers à la racine
# ---------------------------------------------------------------------------
FILES += [
    ("Nouveau dossier (2)/sans titre.docx", "2022-10-17"),
    ("Nouveau dossier (2)/sans titre (2).docx", "2022-10-18"),
    # Racine du service
    ("CV_Martine_DUPONT.pdf", "2019-03-14"),
    ("CV_Camille_MOREAU.pdf", "2020-06-15"),
    ("organigramme service 2023.pptx", "2023-01-09"),
    ("organigramme service 2024.pptx", "2024-01-09"),
    ("Document1.pdf", "2024-02-28"),
    ("Document2.pdf", "2024-03-15"),
    ("scan a trier.pdf", "2024-03-04"),
    ("aaaa.pdf", "2023-08-08"),
    ("note de service 2024-03.pdf", "2024-03-22"),
]


# Dossiers vides
EMPTY_DIRS: list[str] = [
    "Archives 2014",
    "Archives 2015",
    "Archives 2018",
    "Nouveau dossier",
    "Nouveau dossier (3)",
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
