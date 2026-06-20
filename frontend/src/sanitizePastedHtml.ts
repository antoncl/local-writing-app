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

/** Strip presentational attributes + decorative wrappers from pasted
 *  HTML. Returns the cleaned HTML as a string. */
export function sanitizePastedHtml(html: string): string {
  if (!html) return "";
  const doc = new DOMParser().parseFromString(html, "text/html");
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
