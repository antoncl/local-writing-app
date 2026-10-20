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

/** Marks HTML this app's editors put on the clipboard (#2235); see
 *  `AppClipboardMarker` in `lib/editor-core/appClipboard.ts`. */
export const APP_CLIPBOARD_MARKER = "data-lwa-clipboard";

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

// Chrome/Vivaldi append `<br class="Apple-interchange-newline">` when a copied
// selection ends at a line end (Firefox does not). It marks a trailing line
// break, not content, so it must not stop a paste from counting as one whole
// code block (#2568).
function isInterchangeNewline(node: Node): boolean {
  return node instanceof HTMLElement && node.tagName === "BR" && node.classList.contains("Apple-interchange-newline");
}

// Text selected inside a code block — a "copy markdown source" view, or an AI
// chat reply that fenced a note as ```xml / ```markdown — arrives as a SINGLE
// <pre> wrapping the entire paste. Turndown then serializes that <pre> to a fence
// and the whole body renders monospaced (#1622, #2450). These are prose bodies:
// when the whole paste is exactly one code block, whatever its language, it is
// prose shown as source, not a code sample — return its text re-parsed as
// markdown. Returns null when the paste is anything else, so a code block that
// arrives among other prose is kept as code.
function wholePasteCodeBlockText(body: HTMLElement): string | null {
  const kids = Array.from(body.childNodes).filter(
    (node) =>
      // Chromium wraps clipboard HTML in <!--StartFragment--> comments.
      node.nodeType !== Node.COMMENT_NODE &&
      !(node.nodeType === Node.TEXT_NODE && !node.textContent?.trim()) &&
      !isInterchangeNewline(node),
  );
  if (kids.length !== 1) return null;
  const pre = kids[0];
  if (!(pre instanceof HTMLElement) || pre.tagName !== "PRE") return null;
  return pre.textContent ?? "";
}

/** Strip presentational attributes + decorative wrappers from pasted
 *  HTML. Returns the cleaned HTML as a string. */
export function sanitizePastedHtml(html: string): string {
  if (!html) return "";
  const doc = new DOMParser().parseFromString(html, "text/html");
  // The app's own clipboard HTML is already clean, and its inline nodes (a
  // mutation pill, a character mention) are spans identified by data-*
  // attributes the sanitizing below would strip (#2235). Pass it through.
  const markers = doc.body.querySelectorAll(`[${APP_CLIPBOARD_MARKER}]`);
  if (markers.length > 0) {
    for (const marker of Array.from(markers)) marker.remove();
    return doc.body.innerHTML;
  }
  // A paste that is one whole code block is prose shown as source — re-parse it
  // to HTML so it lands as prose, not a monospaced fence.
  const codeBlockText = wholePasteCodeBlockText(doc.body);
  if (codeBlockText !== null) return marked.parse(codeBlockText) as string;
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
