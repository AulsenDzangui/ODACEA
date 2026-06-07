import fs from "node:fs/promises";
import path from "node:path";
import { AppHeader } from "@/components/app-header";
import { StreamingMarkdown } from "@/components/streaming-markdown";
import { MarkdownToc } from "@/components/markdown-toc";

async function loadGuide(): Promise<string> {
  const guidePath = path.join(
    process.cwd(),
    "..",
    "docs",
    "GUIDE_UTILISATEUR.md",
  );
  try {
    const raw = await fs.readFile(guidePath, "utf-8");
    return raw
      .replace(/🔌/g, "{{icon:plug}}")
      .replace(/🔋/g, "{{icon:sliders}}")
      .replace(/💾/g, "{{icon:folder-archive}}")
      .replace(/🗑️?/g, "{{icon:trash}}")
      .replace(/📥/g, "{{icon:download}}");
  } catch {
    return "# Documentation introuvable\n\nLe fichier `GUIDE_UTILISATEUR.md` n'a pas pu être chargé.";
  }
}

export default async function DocsPage() {
  const md = await loadGuide();

  return (
    <div className="flex min-h-screen flex-col">
      <AppHeader />

      <main className="flex-1 px-6 pt-8 pb-6">
        <div className="mx-auto grid max-w-6xl gap-6 md:grid-cols-[220px_minmax(0,1fr)]">
          <MarkdownToc
            text={md}
            className="sticky top-4 self-start"
          />
          <div className="min-w-0">
            <StreamingMarkdown text={md} />
          </div>
        </div>
      </main>
    </div>
  );
}
