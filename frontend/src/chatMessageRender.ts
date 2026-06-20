import { Marked } from "marked";
import katex from "katex";
import DOMPurify from "dompurify";

type MathToken = {
  type: "mathBlock" | "mathInline";
  raw: string;
  tex: string;
};

function renderMath(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex, {
      displayMode,
      throwOnError: false,
      output: "htmlAndMathml",
      strict: false,
    });
  } catch {
    const safe = tex.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return displayMode
      ? `<pre class="katex-error">${safe}</pre>`
      : `<code class="katex-error">${safe}</code>`;
  }
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
      renderer(token: MathToken) {
        return renderMath(token.tex, true);
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
      renderer(token: MathToken) {
        return renderMath(token.tex, false);
      },
    },
  ],
});

export function renderChatContent(text: string): string {
  if (!text) return "";
  // Streaming safety: marked's tokenizers only match math when delimiters close,
  // so an unclosed $...$ at the tail just stays as literal text until the next
  // delta. No pre-pass needed.
  let html: string;
  try {
    html = marked.parse(text) as string;
  } catch {
    const safe = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return `<p>${safe}</p>`;
  }
  return DOMPurify.sanitize(html, {
    ADD_TAGS: ["math", "semantics", "mrow", "mi", "mo", "mn", "ms", "mtext", "mspace", "annotation", "munder", "mover", "munderover", "msub", "msup", "msubsup", "mfrac", "msqrt", "mroot", "mstyle", "merror", "mtable", "mtr", "mtd", "menclose", "mphantom", "mpadded"],
    ADD_ATTR: ["aria-hidden", "class", "style", "mathvariant", "mathcolor", "mathbackground", "displaystyle", "scriptlevel", "lspace", "rspace", "stretchy", "fence", "form", "separator", "accent", "movablelimits", "minsize", "maxsize"],
  });
}
