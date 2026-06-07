"use client";

import { Children, Fragment, isValidElement, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Plug,
  Sliders,
  FolderArchive,
  Trash2,
  Download,
  Copy,
  Check,
  type LucideIcon,
} from "lucide-react";
import { slugify } from "@/lib/markdown/toc";

type Props = {
  text: string;
  className?: string;
};

const DOC_ICONS: Record<string, LucideIcon> = {
  plug: Plug,
  sliders: Sliders,
  "folder-archive": FolderArchive,
  trash: Trash2,
  download: Download,
};

const ICON_TOKEN_RE = /(\{\{icon:[a-z-]+\}\})/g;
const ICON_NAME_RE = /^\{\{icon:([a-z-]+)\}\}$/;

function renderTextWithIcons(s: string): ReactNode {
  if (!s.includes("{{icon:")) return s;
  const parts = s.split(ICON_TOKEN_RE);
  return parts.map((part, i) => {
    const m = part.match(ICON_NAME_RE);
    if (m) {
      const Icon = DOC_ICONS[m[1]];
      if (Icon)
        return (
          <Icon
            key={i}
            aria-hidden="true"
            className="inline-block size-[1em] align-[-0.15em]"
          />
        );
    }
    return <Fragment key={i}>{part}</Fragment>;
  });
}

function withIcons(children: ReactNode): ReactNode {
  return Children.map(children, (c) =>
    typeof c === "string" ? renderTextWithIcons(c) : c,
  );
}

function extractText(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (isValidElement(node)) {
    const props = node.props as { children?: ReactNode };
    return extractText(props.children);
  }
  return "";
}

function headingId(children: ReactNode): string | undefined {
  const id = slugify(extractText(children));
  return id || undefined;
}

function CodeBlock({ children, ...props }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(extractText(children));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Échec de copie presse-papiers ignoré (best-effort).
    }
  };
  return (
    <div className="group relative my-3">
      <pre
        className="overflow-auto rounded-md border border-(--ink-100) bg-(--paper-100) p-3 pr-10 font-mono text-xs text-(--ink-800)"
        {...props}
      >
        {children}
      </pre>
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? "Copié" : "Copier"}
        title={copied ? "Copié" : "Copier"}
        className="absolute right-2 top-2 inline-flex h-7 w-7 items-center justify-center rounded border border-(--ink-100) bg-(--paper-50) text-(--ink-500) opacity-0 transition hover:bg-(--paper-100) hover:text-(--ink-900) focus:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-(--graphite-600) group-hover:opacity-100"
      >
        {copied ? (
          <Check className="h-3.5 w-3.5 text-(--success-700)" />
        ) : (
          <Copy className="h-3.5 w-3.5" />
        )}
      </button>
    </div>
  );
}

const components: Components = {
  h1: ({ children, ...props }) => (
    <h1
      id={headingId(children)}
      className="mt-6 mb-3 scroll-mt-6 text-2xl font-bold tracking-tight text-(--ink-900)"
      {...props}
    >
      {withIcons(children)}
    </h1>
  ),
  h2: ({ children, ...props }) => (
    <h2
      id={headingId(children)}
      className="mt-6 mb-3 scroll-mt-6 border-b border-(--ink-100) pb-1 text-xl font-bold text-(--ink-900)"
      {...props}
    >
      {withIcons(children)}
    </h2>
  ),
  h3: ({ children, ...props }) => (
    <h3
      id={headingId(children)}
      className="mt-5 mb-2 scroll-mt-6 text-lg font-semibold text-(--ink-900)"
      {...props}
    >
      {withIcons(children)}
    </h3>
  ),
  h4: ({ children, ...props }) => (
    <h4
      id={headingId(children)}
      className="mt-4 mb-1 scroll-mt-6 text-base font-semibold text-(--ink-900)"
      {...props}
    >
      {withIcons(children)}
    </h4>
  ),
  p: ({ children, ...props }) => <p className="my-2 leading-relaxed text-(--ink-700)" {...props}>{withIcons(children)}</p>,
  strong: ({ children, ...props }) => <strong className="font-semibold text-(--ink-900)" {...props}>{withIcons(children)}</strong>,
  em: ({ children, ...props }) => <em className="italic" {...props}>{withIcons(children)}</em>,
  ul: (props) => (
    <ul className="my-2 list-disc space-y-1 pl-6" {...props} />
  ),
  ol: (props) => (
    <ol className="my-2 list-decimal space-y-1 pl-6" {...props} />
  ),
  li: ({ children, ...props }) => <li className="leading-relaxed text-(--ink-700)" {...props}>{withIcons(children)}</li>,
  blockquote: ({ children, ...props }) => (
    <blockquote
      className="my-2 border-l-4 border-(--ink-200) bg-(--paper-100) px-3 py-1 italic text-(--ink-700)"
      {...props}
    >
      {withIcons(children)}
    </blockquote>
  ),
  code: ({ className, children, ...props }) => {
    const isInline = !className;
    if (isInline) {
      return (
        <code
          className="rounded border border-(--ink-100) bg-(--paper-100) px-1.5 py-0.5 font-mono text-[0.85em] text-(--ink-800)"
          {...props}
        >
          {withIcons(children)}
        </code>
      );
    }
    return (
      <code className={className} {...props}>
        {withIcons(children)}
      </code>
    );
  },
  pre: ({ children, ...props }) => <CodeBlock {...props}>{children}</CodeBlock>,
  table: (props) => (
    <div className="my-3 overflow-auto rounded-md border border-(--ink-100)">
      <table className="w-full border-collapse text-sm" {...props} />
    </div>
  ),
  thead: (props) => (
    <thead className="bg-(--paper-100)" {...props} />
  ),
  tr: (props) => (
    <tr className="border-b border-(--ink-100) last:border-b-0" {...props} />
  ),
  th: ({ children, ...props }) => (
    <th
      className="px-3 py-1.5 text-left font-semibold text-(--ink-700)"
      {...props}
    >
      {withIcons(children)}
    </th>
  ),
  td: ({ children, ...props }) => (
    <td className="px-3 py-1.5 text-(--ink-700)" {...props}>
      {withIcons(children)}
    </td>
  ),
  hr: () => (
    <hr className="my-4 border-(--ink-100)" />
  ),
  a: (props) => (
    <a
      className="text-(--ink-900) underline underline-offset-3 decoration-(--ink-300) hover:decoration-(--ink-700)"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    />
  ),
};

export function StreamingMarkdown({ text, className }: Props) {
  return (
    <div className={"text-sm text-(--ink-700) " + (className ?? "")}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
