// Quote links (#2498). In a chat about a manuscript scene, a quote in an
// assistant reply that really occurs in that scene's prose becomes a link; the
// click reveals the passage in the scene beside the chat. This module is the
// pure half: the scene's text as the editor shows it, the verification of a
// quote against it, and the post-pass that marks the rendered reply's quotes.
// Verification is what keeps a link honest — a paraphrase never links.

import { normalize } from "@/lib/editor-core/lineEdits";
import { sceneMarkdownToHtml } from "@/lib/utils/markdown";

/** A quote shorter than this (words / characters) never links — an italicized
 *  single word would otherwise link to a common word in the prose. */
const MIN_WORDS = 3;
const MIN_CHARS = 12;

const LEAF_BLOCKS = "p, h1, h2, h3, h4, h5, h6, pre, li, td, th";

/** The scene's prose as the editor shows it: each text block's text, blocks
 *  joined by "\n". HTML comments (mutation / todo / beat markers) vanish with
 *  the markdown→HTML step, exactly as they do in the ProseMirror doc. */
export async function scenePlainText(markdown: string): Promise<string> {
  const html = await sceneMarkdownToHtml(markdown);
  const body = new DOMParser().parseFromString(html, "text/html").body;
  body.querySelectorAll("br").forEach((br) => br.replaceWith("\n"));
  const blocks: string[] = [];
  body.querySelectorAll(LEAF_BLOCKS).forEach((el) => {
    // A list item holding a paragraph (or a nested list) is not itself a leaf.
    if (el.querySelector(LEAF_BLOCKS)) return;
    blocks.push(el.textContent ?? "");
  });
  return blocks.join("\n");
}

/** Strip one pair of surrounding quote marks. */
function unquote(s: string): string {
  const m = /^(?:“([\s\S]*)”|"([\s\S]*)"|„([\s\S]*)”)$/.exec(s);
  return m ? (m[1] ?? m[2] ?? m[3]) : s;
}

let normalizedFor = "";
let normalizedPlain = "";
function normalizedScene(plain: string): string {
  if (plain !== normalizedFor) {
    normalizedFor = plain;
    normalizedPlain = normalize(plain);
  }
  return normalizedPlain;
}

/** The scene's OWN text for `quote`, or null. Typographic quotes/dashes match
 *  their ASCII forms; because that map is 1:1 an index in the normalized scene
 *  is the same index in the original, so the returned text is the doc's own
 *  characters. Occurring more than once is fine — the reveal picks a match. */
export function findQuote(quote: string, plain: string): string | null {
  if (!plain) return null;
  const inner = unquote(quote.trim());
  const piece = inner
    .split(/…|\.{3}/)
    .map((p) => p.replace(/\s+/g, " ").trim())
    .reduce((a, b) => (b.length > a.length ? b : a), "");
  if (piece.length < MIN_CHARS || piece.split(" ").length < MIN_WORDS) return null;
  const at = normalizedScene(plain).indexOf(normalize(piece));
  if (at < 0) return null;
  // The piece has its whitespace collapsed (no "\n"), so a match can't span
  // blocks — the reveal couldn't either.
  return plain.slice(at, at + piece.length);
}

const SKIP_ANCESTORS = "code, pre, a, [data-quote]";

function mark(el: Element, docText: string): void {
  el.classList.add("chat-quote-link");
  el.setAttribute("data-quote", docText);
  el.setAttribute("role", "link");
  el.setAttribute("tabindex", "0");
}

/** Post-pass over a rendered assistant reply's sanitized HTML: marks each
 *  verified quote (an <em>, a blockquote paragraph, or a “…” / "…" run). */
export function linkQuotes(html: string, plain: string): string {
  if (!plain) return html;
  const body = new DOMParser().parseFromString(html, "text/html").body;
  // Never nest links: skip anything inside a marked element or a code/anchor.
  const linkable = (el: Element) => !el.closest(SKIP_ANCESTORS) && !el.querySelector("[data-quote]");

  const elementCandidates = [
    ...body.querySelectorAll("blockquote > p, blockquote > li"),
    ...body.querySelectorAll("em"),
  ];
  for (const el of elementCandidates) {
    if (!linkable(el)) continue;
    const found = findQuote(el.textContent ?? "", plain);
    if (found) mark(el, found);
  }

  const texts: Text[] = [];
  const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) texts.push(n as Text);
  for (const node of texts) {
    if (node.parentElement?.closest(SKIP_ANCESTORS)) continue;
    const text = node.data;
    const runs = [...text.matchAll(/“[^”]{12,}”|"[^"]{12,}"/g)].filter((m) => findQuote(m[0], plain));
    if (runs.length === 0) continue;
    const frag = document.createDocumentFragment();
    let cursor = 0;
    for (const m of runs) {
      const start = m.index ?? 0;
      if (start > cursor) frag.append(text.slice(cursor, start));
      const span = document.createElement("span");
      mark(span, findQuote(m[0], plain)!);
      span.textContent = m[0];
      frag.append(span);
      cursor = start + m[0].length;
    }
    if (cursor < text.length) frag.append(text.slice(cursor));
    node.replaceWith(frag);
  }
  return body.innerHTML;
}
