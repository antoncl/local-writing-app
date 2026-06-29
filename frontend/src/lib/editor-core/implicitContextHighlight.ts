// TipTap extension: highlights lore-name occurrences inline as the user
// types. Companion to the server-side implicit-context expander —
// shows the user which words would feed the journal on send.
//
// Implementation: ProseMirror plugin maintains a DecorationSet by
// walking the doc on every transaction, calling the matcher, and
// emitting inline decorations with a CSS class and entry-id data
// attribute. A single hover popup element is shared per editor view —
// shown when the cursor enters a decoration's DOM node, hidden when it
// leaves.
//
// Performance: per the benchmark at frontend/benchmarks/results.md,
// regex scans at Honorverse-scale finish in microseconds even at 500KB
// documents. We rescan the whole doc per transaction for now —
// incremental rescans (only changed paragraphs) are easy to add later
// if a large project shows pressure.

import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "prosemirror-state";
import { Decoration, DecorationSet } from "prosemirror-view";
import type { Node as PMNode } from "prosemirror-model";
import type { EditorView } from "prosemirror-view";

import { compileMatcher, type CompiledMatcher, type MatchHit, type MatcherEntry } from "@/lib/editor-core/implicitContextMatcher";

const HIGHLIGHT_CLASS = "implicit-context-match";
const POPUP_CLASS = "implicit-context-popup";

export type ImplicitContextOptions = {
  /** Compiled matcher. Pass `null` to disable highlighting (e.g. while
   *  the lore index hasn't loaded yet). The extension watches for
   *  reference changes via setMatcher() rather than reactivity, so the
   *  initial value is fine if you provide an empty matcher. */
  matcher: CompiledMatcher | null;
};

const pluginKey = new PluginKey<DecorationSet>("implicit-context-highlight");

/** Meta key that triggers a forced re-scan even when the document hasn't
 *  changed. Use after mutating extension options.matcher so the new
 *  pattern set takes effect immediately. */
export const REBUILD_META = "implicit-context-rebuild";

/** Walk all text nodes in the doc, run the matcher, build decorations.
 *  Position math: ProseMirror's text-node positions are document-wide;
 *  we add the in-text hit offset to the node's start position. */
function buildDecorations(doc: PMNode, matcher: CompiledMatcher): DecorationSet {
  if (matcher.isEmpty) return DecorationSet.empty;
  const decorations: Decoration[] = [];
  doc.descendants((node, pos) => {
    if (!node.isText) return;
    const text = node.text ?? "";
    if (!text) return;
    const hits = matcher.scan(text);
    for (const hit of hits) {
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
  return DecorationSet.create(doc, decorations);
}

/** Shared popup DOM — one element per editor view, kept hidden until a
 *  decoration is hovered. Reused across hover events to avoid
 *  thrashing the DOM. */
type PopupController = {
  show(target: HTMLElement, entry: MatcherEntry): void;
  hide(): void;
  destroy(): void;
};

function createPopup(): PopupController {
  const el = document.createElement("div");
  el.className = POPUP_CLASS;
  el.setAttribute("role", "tooltip");
  el.style.display = "none";
  document.body.appendChild(el);

  let hideTimer: number | null = null;
  const clearHideTimer = () => {
    if (hideTimer !== null) {
      window.clearTimeout(hideTimer);
      hideTimer = null;
    }
  };

  function position(target: HTMLElement) {
    const rect = target.getBoundingClientRect();
    // Default placement: below the target. If that would clip off the
    // bottom edge, flip above. Horizontal: left-align, clamp to viewport.
    el.style.display = "block";
    el.style.visibility = "hidden"; // measure first
    const popupRect = el.getBoundingClientRect();
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
    el.style.top = `${Math.round(top)}px`;
    el.style.left = `${Math.round(left)}px`;
    el.style.visibility = "visible";
  }

  return {
    show(target, entry) {
      clearHideTimer();
      el.innerHTML = "";
      const titleEl = document.createElement("div");
      titleEl.className = `${POPUP_CLASS}-title`;
      titleEl.textContent = entry.title;
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
      position(target);
    },
    hide() {
      // Short delay so quickly leaving and re-entering doesn't flicker.
      clearHideTimer();
      hideTimer = window.setTimeout(() => {
        el.style.display = "none";
        hideTimer = null;
      }, 80);
    },
    destroy() {
      clearHideTimer();
      el.remove();
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
    return { matcher: null };
  },
  addProseMirrorPlugins() {
    // Capture matcher reference. The extension is recreated when the
    // matcher reference changes via editor.extensionManager update — but
    // for now we read fresh from this.options on each transaction so a
    // mutated `options.matcher` is picked up without full re-init.
    const getMatcher = (): CompiledMatcher | null => this.options.matcher;

    return [
      new Plugin<DecorationSet>({
        key: pluginKey,
        state: {
          init: (_config, state) => {
            const matcher = getMatcher();
            if (!matcher) return DecorationSet.empty;
            return buildDecorations(state.doc, matcher);
          },
          apply: (tr, old) => {
            const matcher = getMatcher();
            if (!matcher || matcher.isEmpty) return DecorationSet.empty;
            const forced = tr.getMeta(REBUILD_META);
            if (!tr.docChanged && !forced) return old;
            // Doc changed (or caller forced a rebuild because the matcher
            // reference changed). Full rescan — sub-millisecond at our
            // scale per the benchmark. Incremental rescan is a v2 win.
            return buildDecorations(tr.doc, matcher);
          },
        },
        props: {
          decorations(state) {
            return pluginKey.getState(state) ?? DecorationSet.empty;
          },
          handleDOMEvents: (() => {
            let popup: PopupController | null = null;
            let currentTarget: HTMLElement | null = null;

            const ensurePopup = (): PopupController => {
              if (!popup) popup = createPopup();
              return popup;
            };

            return {
              mouseover(view: EditorView, event: Event): boolean {
                const matcher = getMatcher();
                if (!matcher) return false;
                const target = findDecorationTarget(event.target, view.dom);
                if (!target || target === currentTarget) return false;
                const id = target.getAttribute("data-entry-id");
                if (!id) return false;
                const entry = matcher.lookup.get(id);
                if (!entry) return false;
                currentTarget = target;
                ensurePopup().show(target, entry);
                return false;
              },
              mouseout(view: EditorView, event: Event): boolean {
                const target = findDecorationTarget(event.target, view.dom);
                if (target !== currentTarget) return false;
                // Only hide if leaving to an element that isn't a child
                // of the decoration.
                const related = (event as MouseEvent).relatedTarget;
                if (related instanceof Node && target?.contains(related)) {
                  return false;
                }
                currentTarget = null;
                popup?.hide();
                return false;
              },
            };
          })(),
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
  return { matcher: compileMatcher(loreEntries, schema) };
}
