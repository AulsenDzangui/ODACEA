"""Extraction d'un sommaire (table des matières) depuis du Markdown.

Porté de `web/lib/markdown/toc.ts`. Utilisé pour afficher un sommaire du
rapport d'audit. Les ancres correspondent aux slugs des titres Markdown.
"""

import re
import unicodedata

_FENCE_RE = re.compile(r"^\s*```")
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def extract_toc(markdown: str) -> list[tuple[int, str, str]]:
    """Retourne une liste de (level, text, id) pour les titres de niveau 1 à 4.

    Les titres à l'intérieur de blocs de code (```) sont ignorés lorsque les
    fences sont appariées (nombre pair).
    """
    lines = markdown.splitlines()

    fence_count = sum(1 for line in lines if _FENCE_RE.match(line))
    track_fences = fence_count > 0 and fence_count % 2 == 0

    entries: list[tuple[int, str, str]] = []
    in_fence = False

    for line in lines:
        if track_fences and _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        m = _HEADING_RE.match(line)
        if not m:
            continue

        level = len(m.group(1))
        text = re.sub(r"[*_`]+", "", m.group(2)).strip()
        if not text:
            continue
        slug = slugify(text)
        if not slug:
            continue
        entries.append((level, text, slug))

    return entries
