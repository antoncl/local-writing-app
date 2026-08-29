// Sanitize HTML coming from the clipboard before TipTap converts it.
//
// External sources (web pages, Word, Google Docs) bring inline styles,
// class names, and Office-specific markup that can't round-trip through
// our Markdown serializer. Stripping these at paste time means what's
// stored matches what's rendered — no surprise font / colour / family
// carryover that survives a save/reload.
//
// We keep structural HTML (paragraphs, headings, lists, tables, blockquotes,
// formatting marks like <strong>/<em>/<a>) — TipTap's schema decides
// which of those it actually accepts. The point here is to remove
// presentational attributes, not to filter the schema.

import { marked } from "marked";

const ATTRS_TO_STRIP = new Set([
  "style",
  "class",
  "id",
  "color",          // legacy HTML attr
  "face",           // legacy HTML attr (<font face>)
  "bgcolor",
  "align",
  "valign",
  "width",          // strip table sizing — let our own CSS govern
  "height",
  "cellpadding",
  "cellspacing",
  "border",
]);

const ELEMENTS_TO_UNWRAP = new Set([
  // Decorative wrappers from web pages that carry no semantics.
  "font",
  "span",
]);

function stripAttributes(el: Element): void {
  for (const attr of Array.from(el.attributes)) {
    const name = attr.name.toLowerCase();
    if (
      ATTRS_TO_STRIP.has(name) ||
      name.startsWith("data-") ||
      name.startsWith("mso-") ||
      name.startsWith("aria-")
    ) {
      el.removeAttribute(attr.name);
    }
  }
}

function unwrap(el: Element): void {
  const parent = el.parentNode;
  if (!parent) return;
  while (el.firstChild) parent.insertBefore(el.firstChild, el);
  parent.removeChild(el);
}

// A whole document copied from a "view / copy markdown source" affordance (or an
// AI chat's code panel) arrives as a SINGLE <pre><code class="language-markdown">
// wrapping the entire paste. Turndown then serializes that <pre> to a ```markdown
// fence and the body renders monospaced (#1622). When the whole paste is exactly
// one such markdown-labelled code block, it is prose shown as source, not a code
// sample — return its text re-parsed as the markdown it is. Returns null when the
// paste is anything else (including a code block in another language, or with no
// language, or code among other prose), so a genuine code sample is never touched.
function wholeDocumentMarkdownSource(body: HTMLElement): string | null {
  const kids = Array.from(body.childNodes).filter(
    (node) => !(node.nodeType === Node.TEXT_NODE && !node.textContent?.trim()),
  );
  if (kids.length !== 1) return null;
  const pre = kids[0];
  if (!(pre instanceof HTMLElement) || pre.tagName !== "PRE") return null;
  const code = pre.querySelector("code");
  const languageClass = (code ?? pre).getAttribute("class") ?? "";
  if (!/\blanguage-(?:markdown|md)\b/.test(languageClass)) return null;
  return (code ?? pre).textContent ?? "";
}

/** Strip presentational attributes + decorative wrappers from pasted
 *  HTML. Returns the cleaned HTML as a string. */
export function sanitizePastedHtml(html: string): string {
  if (!html) return "";
  const doc = new DOMParser().parseFromString(html, "text/html");
  // Before any attribute stripping (which removes the `language-markdown` class
  // the check keys on): a whole-document markdown code block is prose shown as
  // source — re-parse it to HTML so it lands as prose, not a monospaced fence.
  const markdownSource = wholeDocumentMarkdownSource(doc.body);
  if (markdownSource !== null) return marked.parse(markdownSource) as string;
  // First pass: strip attributes from every element.
  for (const el of Array.from(doc.body.querySelectorAll("*"))) {
    stripAttributes(el);
  }
  // Second pass: unwrap purely decorative wrappers (<font>, <span>).
  // Iterate live to handle nested cases (unwrapping a <span> can expose
  // a new <span> child of the same parent).
  let pass = 0;
  while (pass++ < 10) {
    const toUnwrap = Array.from(doc.body.querySelectorAll("font, span"));
    if (toUnwrap.length === 0) break;
    for (const el of toUnwrap) {
      if (ELEMENTS_TO_UNWRAP.has(el.tagName.toLowerCase())) {
        unwrap(el);
      }
    }
  }
  return doc.body.innerHTML;
}
