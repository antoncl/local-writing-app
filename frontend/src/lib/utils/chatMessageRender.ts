import { Marked } from "marked";
import type katexNs from "katex";
import DOMPurify from "dompurify";

type MathToken = {
  type: "mathBlock" | "mathInline";
  raw: string;
  tex: string;
};

let katex: typeof katexNs | null = null;
let katexLoad: Promise<void> | null = null;

// Cheap pre-check: an unescaped `$` is the only thing that can start math.
// Keeps a math-free message from ever triggering the KaTeX download.
const MATH_DELIMITER = /(?<!\\)\$/;
export function containsMath(text: string | null | undefined): boolean {
  return !!text && MATH_DELIMITER.test(text);
}

// Idempotent lazy load of KaTeX JS + CSS. Resolves once the module is ready;
// callers re-render afterwards so the escaped-fallback placeholders upgrade
// to real math.
export function ensureKatexLoaded(): Promise<void> {
  if (katex) return Promise.resolve();
  if (!katexLoad) {
    katexLoad = Promise.all([
      import("katex"),
      import("katex/dist/katex.min.css"),
    ]).then(([mod]) => {
      katex = mod.default;
    });
  }
  return katexLoad;
}

function renderMath(tex: string, displayMode: boolean): string {
  if (katex) {
    try {
      return katex.renderToString(tex, {
        displayMode, throwOnError: false, output: "htmlAndMathml", strict: false,
      });
    } catch {
      // fall through to escaped fallback
    }
  }
  const safe = tex.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return displayMode
    ? `<pre class="katex-error">${safe}</pre>`
    : `<code class="katex-error">${safe}</code>`;
}

const marked = new Marked({ gfm: true, breaks: true });

marked.use({
  extensions: [
    {
      name: "mathBlock",
      level: "block",
      start(src: string) {
        const i = src.indexOf("$$");
        return i < 0 ? undefined : i;
      },
      tokenizer(src: string) {
        const match = /^\$\$([\s\S]+?)\$\$(?:\n|$)/.exec(src);
        if (!match) return undefined;
        const token: MathToken = { type: "mathBlock", raw: match[0], tex: match[1].trim() };
        return token;
      },
      renderer(token) {
        return renderMath((token as MathToken).tex, true);
      },
    },
    {
      name: "mathInline",
      level: "inline",
      start(src: string) {
        const match = /(?:^|[^\\])\$(?!\s|\$)/.exec(src);
        if (!match) return undefined;
        return match.index + (match[0].length - 1);
      },
      tokenizer(src: string) {
        if (src[0] !== "$" || src[1] === "$") return undefined;
        // Inline math: $...$, no newlines, no empty body, no leading/trailing whitespace,
        // closing $ must not be immediately followed by a digit (avoid "$5").
        const match = /^\$([^\s$][^$\n]*?[^\s$]|[^\s$])\$(?!\d)/.exec(src);
        if (!match) return undefined;
        const token: MathToken = { type: "mathInline", raw: match[0], tex: match[1] };
        return token;
      },
      renderer(token) {
        return renderMath((token as MathToken).tex, false);
      },
    },
  ],
});

const FENCE_LINE = /^\s*(```|~~~)/;
const LIST_MARKER_LINE = /^( *)(?:[*+-]|\d{1,9}[.)])[ \t]/;

// #2283: some models (seen with a Gemma build on Ollama) indent EVERY list by
// four spaces, groups separated by blank lines. CommonMark reads a block
// indented ≥4 after a blank line as an indented code block, so the bullets
// render as a <pre> that never wraps. Models fence real code, so when every
// list-marker line (outside fences) sits at ≥4 spaces, shift those lines left
// by the shallowest list indent — nesting keeps its relative depth (4/8 → 0/4).
// Fenced code, and any line indented less than that, is untouched.
export function outdentIndentedLists(text: string): string {
  const lines = text.split("\n");
  let inFence = false;
  let shallowest = Infinity;
  for (const line of lines) {
    if (FENCE_LINE.test(line)) {
      inFence = !inFence;
      continue;
    }
    const marker = inFence ? null : LIST_MARKER_LINE.exec(line);
    if (marker) shallowest = Math.min(shallowest, marker[1].length);
  }
  if (!Number.isFinite(shallowest) || shallowest < 4) return text;
  const pad = " ".repeat(shallowest);
  inFence = false;
  return lines
    .map((line) => {
      if (FENCE_LINE.test(line)) {
        inFence = !inFence;
        return line;
      }
      return !inFence && line.startsWith(pad) ? line.slice(shallowest) : line;
    })
    .join("\n");
}

export function renderChatContent(text: string): string {
  if (!text) return "";
  // Streaming safety: marked's tokenizers only match math when delimiters close,
  // so an unclosed $...$ at the tail just stays as literal text until the next
  // delta. No pre-pass needed.
  let html: string;
  try {
    html = marked.parse(outdentIndentedLists(text)) as string;
  } catch {
    const safe = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return `<p>${safe}</p>`;
  }
  return DOMPurify.sanitize(html, {
    ADD_TAGS: ["math", "semantics", "mrow", "mi", "mo", "mn", "ms", "mtext", "mspace", "annotation", "munder", "mover", "munderover", "msub", "msup", "msubsup", "mfrac", "msqrt", "mroot", "mstyle", "merror", "mtable", "mtr", "mtd", "menclose", "mphantom", "mpadded"],
    ADD_ATTR: ["aria-hidden", "class", "style", "mathvariant", "mathcolor", "mathbackground", "displaystyle", "scriptlevel", "lspace", "rspace", "stretchy", "fence", "form", "separator", "accent", "movablelimits", "minsize", "maxsize"],
  });
}
