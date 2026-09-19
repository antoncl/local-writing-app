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
// a match or leaves the name, the span leaves this view's DOM (a rescan
// re-renders it, and a detached node never fires mouseout), Escape, a
// pointer-down anywhere else — and it goes with the view. The underlined
// name is the app's inline link to the entry: the card's title opens it,
// and so does a modifier-click on the name (Cmd on a Mac, Ctrl elsewhere;
// a plain click keeps placing the caret).
//
// Performance: per the benchmark at frontend/benchmarks/results.md,
// regex scans at Honorverse-scale finish in microseconds even at 500KB
// documents. We rescan the whole doc per transaction for now —
// incremental rescans (only changed paragraphs) are easy to add later
// if a large project shows pressure.

import { Extension } from "@tiptap/core";
import { Plugin, PluginKey, type EditorState } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import type { Node as PMNode } from "@tiptap/pm/model";
import type { EditorView } from "@tiptap/pm/view";

import { anchoredPopover } from "@/lib/actions/anchoredPopover";
import { type CompiledMatcher, type MatcherEntry } from "@/lib/editor-core/implicitContextMatcher";
import { implicitContextOpener } from "@/lib/editor-core/implicitContextOpen";
import type { SummaryValue } from "@/lib/utils/summaryFields";
// The peek-card summary rows' own rules (#2011) — see the file for why this
// lives here instead of growing styles.css past its size-guard cap.
import "@/lib/editor-core/implicitContextPopup.css";

const HIGHLIGHT_CLASS = "implicit-context-match";
const POPUP_CLASS = "implicit-context-popup";
/** How long the card waits after the pointer leaves the name before hiding —
 *  the bridge that lets the pointer cross the gap onto the card. */
export const HIDE_DELAY_MS = 80;

/** Following a name is a modifier-click: Cmd on a Mac, where Ctrl+click is
 *  the secondary click, and Ctrl everywhere else. */
const IS_MAC = typeof navigator !== "undefined" && /Mac|iPhone|iPad|iPod/.test(navigator.platform);
const FOLLOW_HINT = IS_MAC ? "Cmd+click" : "Ctrl+click";
function followsLink(event: MouseEvent): boolean {
  return IS_MAC ? event.metaKey : event.ctrlKey;
}

export type ImplicitContextOptions = {
  /** Compiled matcher. Pass `null` to disable highlighting (e.g. while
   *  the lore index hasn't loaded yet). The extension watches for
   *  reference changes via setMatcher() rather than reactivity, so the
   *  initial value is fine if you provide an empty matcher. */
  matcher: CompiledMatcher | null;
  /** Peek-card summary rows for the hover card (#2011) — optional, and lore
   *  only (scenes/prompts are never matcher entries). Read fresh off
   *  `this.options.describe` at render time, like `matcher`, so the host can
   *  swap it in without recreating the extension. `null`/absent renders the
   *  card exactly as before (title/type/preview, no summary grid). */
  describe?: ((entryId: string) => SummaryValue[]) | null;
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

/** The hover card — one element per editor view, on the page only while it
 *  is shown. `target` is the decoration it is shown for; the card is up
 *  exactly while `target` is set (a pending `hideSoon` is the bridge delay,
 *  nothing more). Placement is `anchoredPopover`'s — the one home for
 *  body-portaled popovers: it portals the element, flips and clamps it, and
 *  re-pins it on scroll and resize. */
type HoverCard = {
  readonly target: HTMLElement | null;
  show(target: HTMLElement, entry: MatcherEntry): void;
  /** Re-pin to the anchor after the text around it reflowed. */
  refresh(): void;
  /** Cancel a pending `hideSoon` — the pointer came back (to the name or onto
   *  the card) within the bridge delay. */
  keep(): void;
  /** Hide after the bridge delay unless kept. A no-op when nothing is shown
   *  or the delay is already running — the pointer sweeping across text that
   *  is not a match must not keep postponing it. */
  hideSoon(): void;
  hide(): void;
  destroy(): void;
};

function createHoverCard(getDescribe: () => ((entryId: string) => SummaryValue[]) | null): HoverCard {
  const el = document.createElement("div");
  el.className = POPUP_CLASS;
  el.setAttribute("role", "dialog");
  let target: HTMLElement | null = null;
  let placement: ReturnType<typeof anchoredPopover> | null = null;
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
    placement?.destroy();
    placement = null;
    document.removeEventListener("keydown", onKeydown, true);
    document.removeEventListener("pointerdown", onPointerDown, true);
  }

  function hideSoon() {
    if (!target || hideTimer !== null) return;
    hideTimer = window.setTimeout(hide, HIDE_DELAY_MS);
  }

  // Escape and a pointer-down anywhere but the card dismiss it — on the
  // document, since hovering never focuses the editor. Escape is consumed:
  // the keypress that closes the card must not also close the dialog or menu
  // the editor sits in.
  function onKeydown(event: KeyboardEvent) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    hide();
  }
  function onPointerDown(event: Event) {
    if (!(event.target instanceof Node) || !el.contains(event.target)) hide();
  }

  // The bridge: crossing onto the card keeps it, leaving it hides it.
  el.addEventListener("mouseenter", clearHideTimer);
  el.addEventListener("mouseleave", hideSoon);

  function render(entry: MatcherEntry) {
    el.innerHTML = "";
    el.setAttribute("aria-label", entry.title);
    const open = implicitContextOpener.open;
    const titleEl = document.createElement(open ? "button" : "div");
    titleEl.className = `${POPUP_CLASS}-title`;
    titleEl.textContent = entry.title;
    if (open && titleEl instanceof HTMLButtonElement) {
      titleEl.type = "button";
      titleEl.classList.add(`${POPUP_CLASS}-open`);
      titleEl.title = `Open this entry (${FOLLOW_HINT} on the name does too)`;
      titleEl.addEventListener("click", () => {
        hide();
        open(entry.id);
      });
    }
    el.appendChild(titleEl);
    if (entry.entryType) {
      const typeEl = document.createElement("div");
      typeEl.className = `${POPUP_CLASS}-type`;
      typeEl.textContent = entry.entryType;
      el.appendChild(typeEl);
    }
    if (entry.preview) {
      const previewEl = document.createElement("div");
      previewEl.className = `${POPUP_CLASS}-preview`;
      previewEl.textContent = entry.preview;
      el.appendChild(previewEl);
    }
    // Peek-card summary rows (#2011) — the same field-grid content a
    // reference's peek card shows, appended after the preview. Lore only:
    // `describe` is wired from loreEntries + schema; absent/empty is a no-op.
    const rows = getDescribe()?.(entry.id) ?? [];
    if (rows.length > 0) {
      const summaryEl = document.createElement("div");
      summaryEl.className = `${POPUP_CLASS}-summary`;
      for (const row of rows) {
        const rowEl = document.createElement("div");
        rowEl.className = `${POPUP_CLASS}-summary-row`;
        const labelEl = document.createElement("span");
        labelEl.className = `${POPUP_CLASS}-summary-label`;
        labelEl.textContent = row.label;
        const valueEl = document.createElement("span");
        valueEl.className = `${POPUP_CLASS}-summary-value`;
        valueEl.textContent = row.text;
        rowEl.append(labelEl, valueEl);
        summaryEl.appendChild(rowEl);
      }
      el.appendChild(summaryEl);
    }
  }

  return {
    get target() {
      return target;
    },
    show(next, entry) {
      clearHideTimer();
      target = next;
      render(entry);
      if (placement) {
        placement.update({ anchor: next });
        return;
      }
      placement = anchoredPopover(el, { anchor: next });
      document.addEventListener("keydown", onKeydown, true);
      document.addEventListener("pointerdown", onPointerDown, true);
    },
    refresh() {
      placement?.update({ anchor: target });
    },
    keep: clearHideTimer,
    hideSoon,
    hide,
    destroy: hide,
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
    return { matcher: null, describe: null };
  },
  addProseMirrorPlugins() {
    // Capture matcher reference. The extension is recreated when the
    // matcher reference changes via editor.extensionManager update — but
    // for now we read fresh from this.options on each transaction so a
    // mutated `options.matcher` is picked up without full re-init.
    const getMatcher = (): CompiledMatcher | null => this.options.matcher;
    const getDescribe = (): ((entryId: string) => SummaryValue[]) | null => this.options.describe ?? null;
    // One card per plugin instance, i.e. per editor view.
    const card = createHoverCard(getDescribe);

    const entryOf = (target: HTMLElement | null): MatcherEntry | undefined => {
      const id = target?.getAttribute("data-entry-id");
      return id ? getMatcher()?.lookup.get(id) : undefined;
    };
    /** The entry a modifier-click on `eventTarget` follows, if any. */
    const followed = (view: EditorView, event: Event): MatcherEntry | undefined => {
      if (!followsLink(event as MouseEvent) || !implicitContextOpener.open) return undefined;
      return entryOf(findDecorationTarget(event.target, view.dom));
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
            if (!card.target) return;
            // The anchor left this view's DOM (a rescan re-rendered the span,
            // and a detached node never fires mouseout): the card's claim is
            // stale. Still attached through an edit elsewhere, it only moved.
            if (!view.dom.contains(card.target)) card.hide();
            else if (view.state.doc !== previous.doc) card.refresh();
          },
          destroy: () => card.destroy(),
        }),
        props: {
          decorations(state) {
            return pluginKey.getState(state)?.decorations ?? DecorationSet.empty;
          },
          handleDOMEvents: {
            mouseover(view: EditorView, event: Event): boolean {
              if (!getMatcher()) return false;
              const target = findDecorationTarget(event.target, view.dom);
              if (target && target === card.target) {
                card.keep();
                return false;
              }
              const entry = entryOf(target);
              // Over text that is not a match — including the text that
              // replaced a re-rendered span the pointer never left.
              if (!target || !entry) card.hideSoon();
              else card.show(target, entry);
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
            // Following a name is not placing the caret: claim the mousedown
            // so ProseMirror's own handler (the selection, `handleClickOn`)
            // never sees the gesture, then open on the click that completes it.
            mousedown(view: EditorView, event: Event): boolean {
              if (!followed(view, event)) return false;
              event.preventDefault();
              return true;
            },
            click(view: EditorView, event: Event): boolean {
              const entry = followed(view, event);
              if (!entry) return false;
              card.hide();
              implicitContextOpener.open?.(entry.id);
              return true;
            },
          },
        },
      }),
    ];
  },
});
