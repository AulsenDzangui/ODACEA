"""Enrichissement mécanique des descriptions à partir des binaires.

Étape de préparation **optionnelle**, exécutée en local sur la machine de
l'archiviste, **avant** l'audit. Elle lit les fichiers bureautiques référencés
par la colonne `File` du CSV et en extrait des métadonnées **déterministes**
(propriétés du document, mots-clés, premières lignes de texte) qu'elle écrit
dans `Content.Description`. Cette colonne est ensuite consommée telle quelle par
AUD-001 et CLA-001 (option « Inclure la description »).

Particularité assumée : contrairement au reste du moteur — qui ne lit que des
métadonnées de chemin/nom/date —, cette étape **ouvre le contenu** des fichiers.
C'est un choix explicite de l'utilisateur : l'étape est facultative, aucune
donnée ne quitte la machine, et l'appelant (CLI/backend) doit afficher un
message clair sur l'accès aux données avant de la lancer.

Aucun appel LLM, aucune OCR : seuls le texte déjà présent dans le fichier
(couche texte des PDF, corps des .docx, etc.) et les propriétés embarquées sont
exploités. Un PDF scanné sans couche texte ne produit donc rien — c'est normal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# Extensions traitées (extraction mécanique de texte/propriétés possible).
# Les autres (jpg, png, zip, …) sont ignorées : pas de texte exploitable
# sans OCR, hors périmètre de l'enrichissement mécanique.
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx"}

# Longueur par défaut de la description produite (budget tokens en aval).
DEFAULT_MAX_CHARS = 300
# Nombre de premières lignes/paragraphes de corps de texte retenus.
_TEXT_SNIPPET_PARAGRAPHS = 3
_TEXT_SNIPPET_CHARS = 220


# ── Rapport ──────────────────────────────────────────────────────────────────

@dataclass
class EnrichReport:
    total_items: int = 0
    enriched: int = 0          # description écrite
    already_filled: int = 0    # description existante préservée (sans --overwrite)
    no_text: int = 0           # fichier lu mais rien d'exploitable (ex. PDF scanné)
    unsupported: int = 0       # extension hors périmètre (jpg, …)
    missing: int = 0           # binaire introuvable sous source_root
    errors: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        out = [
            f"{self.enriched} description(s) écrite(s) sur {self.total_items} item(s)",
        ]
        if self.already_filled:
            out.append(f"{self.already_filled} description(s) existante(s) préservée(s)")
        if self.no_text:
            out.append(f"{self.no_text} fichier(s) sans texte exploitable (PDF scanné, vide…)")
        if self.unsupported:
            out.append(f"{self.unsupported} fichier(s) ignoré(s) (format non bureautique)")
        if self.missing:
            out.append(f"{self.missing} binaire(s) introuvable(s) sous la racine")
        if self.errors:
            out.append(f"{len(self.errors)} erreur(s) de lecture")
        return out


# ── Utilitaires ──────────────────────────────────────────────────────────────

def _clean(text: str | None) -> str:
    """Normalise un fragment : espaces compactés, retours ligne supprimés."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def _resolve(source_root: Path, file_value: str) -> Path:
    """Résout un chemin `File` (séparateurs Windows possibles) sous la racine."""
    parts = [p for p in file_value.replace("\\", "/").split("/") if p not in ("", ".")]
    return source_root.joinpath(*parts)


def _is_noise_title(title: str, filename: str) -> bool:
    """Un « titre interne » égal au nom de fichier ou à un libellé d'outil
    n'apporte rien — on l'écarte pour ne pas polluer la description."""
    t = title.lower().strip()
    if not t:
        return True
    if t == filename.lower() or t == Path(filename).stem.lower():
        return True
    # Titres génériques produits par les suites bureautiques / scanners
    if t.startswith("microsoft word -"):
        return True
    return t in (
        "document", "presentation", "classeur",
        "fichier pdf", "fichier", "untitled", "sans titre",
    )


def _plausible_snippet(raw: str | None) -> str:
    """Nettoie un extrait de corps de texte et le rejette s'il ne ressemble
    pas à de la langue naturelle.

    Certains PDF (polices à encodage non standard, sans table ToUnicode) font
    extraire à pypdf des codes bruts illisibles (« 3$<*Y 05'=$1… »). Ce bruit
    serait pire que rien dans Content.Description — on le détecte via le ratio
    de caractères alphabétiques sur les caractères non-espace.
    """
    text = _clean(raw)
    if not text:
        return ""
    non_space = [c for c in text if not c.isspace()]
    if not non_space:
        return ""
    alpha_ratio = sum(c.isalpha() for c in non_space) / len(non_space)
    if alpha_ratio < 0.6:
        return ""
    return text[:_TEXT_SNIPPET_CHARS]


# ── Extracteurs par format ───────────────────────────────────────────────────
# Chacun retourne un dict ordonné de champs {label: valeur}. Import paresseux :
# une dépendance manquante n'empêche que son format, pas tout l'enrichissement.

def _extract_pdf(path: Path) -> dict[str, str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    fields: dict[str, str] = {}
    meta = reader.metadata or {}
    for label, key in (("Sujet", "/Subject"), ("Mots-clés", "/Keywords"), ("Auteur", "/Author")):
        val = _clean(meta.get(key))
        if val:
            fields[label] = val
    title = _clean(meta.get("/Title"))
    if title and not _is_noise_title(title, path.name):
        fields["Titre interne"] = title

    # Couche texte des premières pages (vide si PDF image/scanné, rejetée si
    # encodage de police illisible).
    for page in reader.pages[:2]:
        try:
            snippet = _plausible_snippet(page.extract_text())
        except Exception:
            snippet = ""
        if snippet:
            fields["Extrait"] = snippet
            break
    return fields


def _extract_docx(path: Path) -> dict[str, str]:
    from docx import Document

    doc = Document(str(path))
    fields: dict[str, str] = {}
    props = doc.core_properties
    for label, val in (
        ("Titre interne", props.title), ("Sujet", props.subject),
        ("Mots-clés", props.keywords), ("Auteur", props.author),
    ):
        clean = _clean(val)
        if not clean:
            continue
        if label == "Titre interne" and _is_noise_title(clean, path.name):
            continue
        fields[label] = clean

    paragraphs = []
    for para in doc.paragraphs:
        text = _clean(para.text)
        if text:
            paragraphs.append(text)
        if len(paragraphs) >= _TEXT_SNIPPET_PARAGRAPHS:
            break
    snippet = _plausible_snippet(" ".join(paragraphs))
    if snippet:
        fields["Extrait"] = snippet
    return fields


def _extract_xlsx(path: Path) -> dict[str, str]:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    fields: dict[str, str] = {}
    props = wb.properties
    for label, val in (
        ("Titre interne", props.title), ("Sujet", props.subject),
        ("Mots-clés", props.keywords), ("Auteur", props.creator),
    ):
        clean = _clean(val)
        if not clean:
            continue
        if label == "Titre interne" and _is_noise_title(clean, path.name):
            continue
        fields[label] = clean
    sheets = [s for s in wb.sheetnames if _clean(s)]
    if sheets:
        fields["Feuilles"] = ", ".join(sheets[:8])
    wb.close()
    return fields


def _extract_pptx(path: Path) -> dict[str, str]:
    from pptx import Presentation

    prs = Presentation(str(path))
    fields: dict[str, str] = {}
    props = prs.core_properties
    for label, val in (
        ("Titre interne", props.title), ("Sujet", props.subject),
        ("Mots-clés", props.keywords), ("Auteur", props.author),
    ):
        clean = _clean(val)
        if not clean:
            continue
        if label == "Titre interne" and _is_noise_title(clean, path.name):
            continue
        fields[label] = clean
    # Texte du premier slide porteur de contenu.
    for slide in prs.slides:
        texts = [_clean(sh.text) for sh in slide.shapes if sh.has_text_frame]
        snippet = _plausible_snippet(" ".join(t for t in texts if t))
        if snippet:
            fields["Extrait"] = snippet
            break
    return fields


_EXTRACTORS = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
    ".xlsx": _extract_xlsx,
    ".pptx": _extract_pptx,
}


def _format_description(fields: dict[str, str], max_chars: int) -> str:
    """Assemble les champs en une ligne compacte `Label : valeur · …`."""
    parts = [f"{label} : {val}" for label, val in fields.items() if val]
    desc = " · ".join(parts)
    if len(desc) > max_chars:
        desc = desc[: max_chars - 1].rstrip() + "…"
    return desc


# ── API publique ─────────────────────────────────────────────────────────────

def enrich_descriptions(
    df: pd.DataFrame,
    source_root: Path,
    *,
    overwrite: bool = False,
    max_chars: int = DEFAULT_MAX_CHARS,
    on_progress=None,
) -> tuple[pd.DataFrame, EnrichReport]:
    """Remplit `Content.Description` des Items à partir des binaires.

    - Ne traite que les lignes `Content.DescriptionLevel == "Item"`.
    - Ne touche pas aux descriptions déjà renseignées, sauf `overwrite=True`.
    - Tolérante : un fichier illisible/absent n'interrompt pas le lot ; il est
      comptabilisé dans le rapport.

    Retourne `(df_enrichi, rapport)`. Le DataFrame est une copie ; l'original
    n'est jamais modifié.
    """
    result = df.copy()
    report = EnrichReport()

    if "Content.Description" not in result.columns:
        result["Content.Description"] = ""
    desc = result["Content.Description"].fillna("")

    is_item = result.get("Content.DescriptionLevel") == "Item"
    item_idx = result.index[is_item] if is_item is not False else result.index[[]]

    for i in item_idx:
        report.total_items += 1
        file_value = _clean(result.at[i, "File"]) if "File" in result.columns else ""
        existing = _clean(desc.at[i])

        if existing and not overwrite:
            report.already_filled += 1
            continue
        if not file_value or file_value == ".":
            continue

        ext = Path(file_value).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            report.unsupported += 1
            continue

        target = _resolve(source_root, file_value)
        if not target.is_file():
            report.missing += 1
            continue

        if on_progress:
            on_progress(file_value)

        try:
            fields = _EXTRACTORS[ext](target)
        except Exception as e:  # lecture/parse échoué : on isole, on continue
            report.errors.append(f"{file_value} : {type(e).__name__} {e}")
            continue

        description = _format_description(fields, max_chars)
        if not description:
            report.no_text += 1
            continue

        result.at[i, "Content.Description"] = description
        report.enriched += 1

    return result, report
