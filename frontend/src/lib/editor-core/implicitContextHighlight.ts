// TipTap extension: highlights lore-name occurrences inline as the user
// types. Companion to the server-side implicit-context expander —
// shows the user which words would feed the journal on send.
//
// Implementation: ProseMirror plugin maintains a DecorationSet by
// walking the doc on every transaction, calling the matcher, and
// emitting inline decorations with a CSS class and entry-id data
// attribute. A single hover card is shared per editor view (#1923): it is
// shown for exactly one attached decoration under the pointer, and hides
// the moment that stops being true — the pointer moves to text that is not
// a match or leaves the editor, the document changes under it (typing
// re-renders the span, so no mouseout ever comes), Escape, a scroll — and
// it goes with the view. The underlined name is the app's inline link to
// the entry: the card's title opens it, and so does Ctrl/Cmd+click on the
// name (a plain click keeps placing the caret).
//
// Performance: per the benchmark at frontend/benchmarks/results.md,
// regex scans at Honorverse-scale finish in microseconds even at 500KB
// documents. We rescan the whole doc per transaction for now —
// incremental rescans (only changed paragraphs) are easy to add later
// if a large project shows pressure.

import { Extension } from "@tiptap/core";
import { Plugin, PluginKey, type EditorState } from "prosemirror-state";
import { Decoration, DecorationSet } from "prosemirror-view";
import type { Node as PMNode } from "prosemirror-model";
import type { EditorView } from "prosemirror-view";

import { compileMatcher, type CompiledMatcher, type MatchHit, type MatcherEntry } from "@/lib/editor-core/implicitContextMatcher";

const HIGHLIGHT_CLASS = "implicit-context-match";
const POPUP_CLASS = "implicit-context-popup";
/** How long the card waits after the pointer leaves the name before hiding —
 *  the bridge that lets the pointer cross the gap onto the card. */
const HIDE_DELAY_MS = 80;

export type ImplicitContextOptions = {
  /** Compiled matcher. Pass `null` to disable highlighting (e.g. while
   *  the lore index hasn't loaded yet). The extension watches for
   *  reference changes via setMatcher() rather than reactivity, so the
   *  initial value is fine if you provide an empty matcher. */
  matcher: CompiledMatcher | null;
  /** Follow a match to its entry: called with the entry id from the card's
   *  title and from Ctrl/Cmd+click on the underlined name. `null` makes the
   *  card read-only (no title link, no modifier click). */
  openEntry: ((entryId: string) => void) | null;
};

/** What one scan produced: the decorations to paint, and the distinct entry
 *  ids they were painted for — the *dynamic context* (#439).
 *
 *  The ids are a by-product of the decoration walk rather than a second scan,
 *  and that is the point: the snapshot witness records exactly the entries the
 *  author can see underlined. A separate pass (here or on the backend) would be
 *  a second matcher that has to agree with this one, and every disagreement
 *  between them would surface as drift on a scene nobody touched. */
export type ScanState = {
  decorations: DecorationSet;
  /** Document order, deduplicated. Order is stable so the payload does not
   *  churn between saves. */
  entityIds: string[];
};

const EMPTY_SCAN: ScanState = { decorations: DecorationSet.empty, entityIds: [] };

const pluginKey = new PluginKey<ScanState>("implicit-context-highlight");

/** Meta key that triggers a forced re-scan even when the document hasn't
 *  changed. Use after mutating extension options.matcher so the new
 *  pattern set takes effect immediately. */
export const REBUILD_META = "implicit-context-rebuild";

/** The entry ids currently highlighted in this editor's document.
 *
 *  Empty when the extension is absent or the matcher has not compiled yet,
 *  which is *not* the same as "the prose mentions nothing" — a caller that
 *  needs the distinction must check whether the editor is ready first. */
export function implicitContextIds(state: EditorState): string[] {
  return pluginKey.getState(state)?.entityIds ?? [];
}

/** Walk all text nodes in the doc, run the matcher, build decorations.
 *  Position math: ProseMirror's text-node positions are document-wide;
 *  we add the in-text hit offset to the node's start position. */
function buildScan(doc: PMNode, matcher: CompiledMatcher): ScanState {
  if (matcher.isEmpty) return EMPTY_SCAN;
  const decorations: Decoration[] = [];
  const entityIds: string[] = [];
  const seen = new Set<string>();
  doc.descendants((node, pos) => {
    if (!node.isText) return;
    const text = node.text ?? "";
    if (!text) return;
    const hits = matcher.scan(text);
    for (const hit of hits) {
      if (!seen.has(hit.entryId)) {
        seen.add(hit.entryId);
        entityIds.push(hit.entryId);
      }
      const entry = matcher.lookup.get(hit.entryId);
      const attrs: Record<string, string> = {
        class: HIGHLIGHT_CLASS,
        "data-entry-id": hit.entryId,
      };
      // Per-entity color via inline CSS custom property — the `.implicit-
      // context-match` rule reads var(--entity-color, <fallback>). Set
      // only when the matcher resolved a color so the fallback kicks in
      // for entries without a swatch.
      if (entry?.colorHex) {
        attrs.style = `--entity-color: ${entry.colorHex}`;
      }
      decorations.push(Decoration.inline(pos + hit.start, pos + hit.end, attrs));
    }
  });
  return { decorations: DecorationSet.create(doc, decorations), entityIds };
}

/** The hover card — one DOM element per editor view, created on the first
 *  hover and kept until the view goes. `target` is the decoration it is shown
 *  for; the card is visible exactly while `target` is set (a pending
 *  `hideSoon` is the bridge delay, nothing more). */
type HoverCard = {
  readonly target: HTMLElement | null;
  show(target: HTMLElement, entry: MatcherEntry): void;
  /** Cancel a pending `hideSoon` — the pointer came back (to the name or onto
   *  the card) within the bridge delay. */
  keep(): void;
  /** Hide after the bridge delay unless kept. A no-op when nothing is shown. */
  hideSoon(): void;
  hide(): void;
  destroy(): void;
};

function createHoverCard(openEntry: () => ImplicitContextOptions["openEntry"]): HoverCard {
  let el: HTMLDivElement | null = null;
  let target: HTMLElement | null = null;
  let hideTimer: number | null = null;

  const clearHideTimer = () => {
    if (hideTimer !== null) {
      window.clearTimeout(hideTimer);
      hideTimer = null;
    }
  };

  function hide() {
    clearHideTimer();
    if (!target) return;
    target = null;
    window.removeEventListener("scroll", hide, true);
    if (el) el.style.display = "none";
  }

  function hideSoon() {
    if (!target) return;
    clearHideTimer();
    hideTimer = window.setTimeout(hide, HIDE_DELAY_MS);
  }

  function ensureElement(): HTMLDivElement {
    if (el) return el;
    el = document.createElement("div");
    el.className = POPUP_CLASS;
    el.style.display = "none";
    // The bridge: crossing onto the card keeps it, leaving it hides it.
    el.addEventListener("mouseenter", () => clearHideTimer());
    el.addEventListener("mouseleave", () => hideSoon());
    document.body.appendChild(el);
    return el;
  }

  function position(card: HTMLDivElement, anchor: HTMLElement) {
    const rect = anchor.getBoundingClientRect();
    // Default placement: below the target. If that would clip off the
    // bottom edge, flip above. Horizontal: left-align, clamp to viewport.
    card.style.display = "block";
    card.style.visibility = "hidden"; // measure first
    const popupRect = card.getBoundingClientRect();
    const vh = window.innerHeight;
    const vw = window.innerWidth;
    let top = rect.bottom + 6;
    if (top + popupRect.height > vh - 8) {
      top = rect.top - popupRect.height - 6;
    }
    let left = rect.left;
    if (left + popupRect.width > vw - 8) {
      left = vw - popupRect.width - 8;
    }
    if (left < 8) left = 8;
    card.style.top = `${Math.round(top)}px`;
    card.style.left = `${Math.round(left)}px`;
    card.style.visibility = "visible";
  }

  function render(card: HTMLDivElement, entry: MatcherEntry) {
    card.innerHTML = "";
    const open = openEntry();
    if (open) {
      const titleEl = document.createElement("button");
      titleEl.type = "button";
      titleEl.className = `${POPUP_CLASS}-title ${POPUP_CLASS}-open`;
      titleEl.textContent = entry.title;
      titleEl.title = "Open this entry (Ctrl+click the name does too)";
      titleEl.setAttribute("aria-label", `Open ${entry.title}`);
      titleEl.addEventListener("click", () => {
        hide();
        open(entry.id);
      });
      card.appendChild(titleEl);
    } else {
      const titleEl = document.createElement("div");
      titleEl.className = `${POPUP_CLASS}-title`;
      titleEl.textContent = entry.title;
      card.appendChild(titleEl);
    }
    if (entry.entryType) {
      const typeEl = document.createElement("div");
      typeEl.className = `${POPUP_CLASS}-type`;
      typeEl.textContent = entry.entryType;
      card.appendChild(typeEl);
    }
    if (entry.preview) {
      const previewEl = document.createElement("div");
      previewEl.className = `${POPUP_CLASS}-preview`;
      previewEl.textContent = entry.preview;
      card.appendChild(previewEl);
    }
  }

  return {
    get target() {
      return target;
    },
    show(next, entry) {
      clearHideTimer();
      const card = ensureElement();
      if (!target) window.addEventListener("scroll", hide, true);
      target = next;
      render(card, entry);
      position(card, next);
    },
    keep: clearHideTimer,
    hideSoon,
    hide,
    destroy() {
      hide();
      el?.remove();
      el = null;
    },
  };
}

/** Find the nearest ancestor element matching the decoration class —
 *  the event target might be a descendant (e.g. an emoji span). */
function findDecorationTarget(target: EventTarget | null, editorRoot: Element): HTMLElement | null {
  let node: Node | null = target as Node | null;
  while (node && node !== editorRoot) {
    if (node instanceof HTMLElement && node.classList.contains(HIGHLIGHT_CLASS)) {
      return node;
    }
    node = node.parentNode;
  }
  return null;
}

export const ImplicitContextHighlight = Extension.create<ImplicitContextOptions>({
  name: "implicitContextHighlight",
  addOptions() {
    return { matcher: null, openEntry: null };
  },
  addProseMirrorPlugins() {
    // Capture matcher reference. The extension is recreated when the
    // matcher reference changes via editor.extensionManager update — but
    // for now we read fresh from this.options on each transaction so a
    // mutated `options.matcher` is picked up without full re-init.
    const getMatcher = (): CompiledMatcher | null => this.options.matcher;
    const getOpenEntry = (): ImplicitContextOptions["openEntry"] => this.options.openEntry;
    // One card per plugin instance, i.e. per editor view.
    const card = createHoverCard(getOpenEntry);

    const entryUnder = (view: EditorView, eventTarget: EventTarget | null) => {
      const target = findDecorationTarget(eventTarget, view.dom);
      const id = target?.getAttribute("data-entry-id");
      const entry = id ? getMatcher()?.lookup.get(id) : undefined;
      return target && entry ? { target, entry } : null;
    };

    return [
      new Plugin<ScanState>({
        key: pluginKey,
        state: {
          init: (_config, state) => {
            const matcher = getMatcher();
            if (!matcher) return EMPTY_SCAN;
            return buildScan(state.doc, matcher);
          },
          apply: (tr, old) => {
            const matcher = getMatcher();
            if (!matcher || matcher.isEmpty) return EMPTY_SCAN;
            const forced = tr.getMeta(REBUILD_META);
            if (!tr.docChanged && !forced) return old;
            // Doc changed (or caller forced a rebuild because the matcher
            // reference changed). Full rescan — sub-millisecond at our
            // scale per the benchmark. Incremental rescan is a v2 win.
            return buildScan(tr.doc, matcher);
          },
        },
        view: () => ({
          update: (view, previous) => {
            // Typing re-renders the hovered span, and a detached node never
            // fires mouseout — the card's anchor is gone, so is the card.
            if (view.state.doc !== previous.doc || (card.target && !view.dom.contains(card.target))) card.hide();
          },
          destroy: () => card.destroy(),
        }),
        props: {
          decorations(state) {
            return pluginKey.getState(state)?.decorations ?? DecorationSet.empty;
          },
          handleDOMEvents: {
            mouseover(view: EditorView, event: Event): boolean {
              const hit = entryUnder(view, event.target);
              if (!hit) {
                // Over text that is not a match — including the text that
                // replaced a re-rendered span the pointer never left.
                card.hideSoon();
              } else if (hit.target === card.target) {
                card.keep();
              } else {
                card.show(hit.target, hit.entry);
              }
              return false;
            },
            mouseout(view: EditorView, event: Event): boolean {
              const target = findDecorationTarget(event.target, view.dom);
              if (!target || target !== card.target) return false;
              // Leaving to a child of the name is not leaving the name.
              const related = (event as MouseEvent).relatedTarget;
              if (related instanceof Node && target.contains(related)) return false;
              card.hideSoon();
              return false;
            },
            mouseleave(): boolean {
              card.hideSoon();
              return false;
            },
            keydown(_view: EditorView, event: Event): boolean {
              if ((event as KeyboardEvent).key === "Escape") card.hide();
              return false;
            },
            click(view: EditorView, event: Event): boolean {
              const mouse = event as MouseEvent;
              if (!mouse.ctrlKey && !mouse.metaKey) return false;
              const open = getOpenEntry();
              const hit = open ? entryUnder(view, event.target) : null;
              if (!hit) return false;
              event.preventDefault();
              card.hide();
              open?.(hit.entry.id);
              return true;
            },
          },
        },
      }),
    ];
  },
});

/** Helper: build options for a project's current lore set. Wraps the
 *  matcher compile so callers don't need to import it directly.
 *  Pass the metadataSchema so the matcher can resolve per-entry colors
 *  for the highlight decorations. */
export function buildImplicitContextOptions(
  loreEntries: Parameters<typeof compileMatcher>[0],
  schema: Parameters<typeof compileMatcher>[1] = null,
): ImplicitContextOptions {
  return { matcher: compileMatcher(loreEntries, schema), openEntry: null };
}
