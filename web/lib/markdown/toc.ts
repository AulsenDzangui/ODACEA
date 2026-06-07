export type TocEntry = {
  level: 1 | 2 | 3 | 4;
  text: string;
  id: string;
};

const FENCE_RE = /^\s*```/;
const HEADING_RE = /^(#{1,4})\s+(.+?)\s*#*\s*$/;

export function slugify(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function extractToc(markdown: string): TocEntry[] {
  const lines = markdown.split(/\r?\n/);

  let fenceCount = 0;
  for (const line of lines) if (FENCE_RE.test(line)) fenceCount++;
  const trackFences = fenceCount > 0 && fenceCount % 2 === 0;

  const entries: TocEntry[] = [];
  let inFence = false;

  for (const line of lines) {
    if (trackFences && FENCE_RE.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;

    const m = HEADING_RE.exec(line);
    if (!m) continue;

    const level = m[1].length as 1 | 2 | 3 | 4;
    const text = m[2].replace(/[*_`]+/g, "").trim();
    if (!text) continue;

    const id = slugify(text);
    if (!id) continue;

    entries.push({ level, text, id });
  }

  return entries;
}
