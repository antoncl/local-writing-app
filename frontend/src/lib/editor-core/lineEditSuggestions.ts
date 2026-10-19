/** Reviewing a model's line edits (#2460) or lore-check notes (ADR-0098) in place.
 *
 *  The placed items live in this plugin's state, NOT in the document: the text
 *  stays untouched until an edit is accepted (a note never changes it). What an
 *  item looks like and which keys act on it is the run's `ReviewKind`
 *  (reviewKinds/edits.ts, reviewKinds/notes.ts); this plugin is the one shared
 *  surface. One item is the CURRENT one (stronger tint): clicking selects it, and
 *  its decision card / the Alt-keys step through them and resolve the current
 *  one. Positions are mapped through every transaction, and an item is dropped
 *  once the writer edits inside it (its range no longer holds the quoted text). */
import { Extension } from "@tiptap/core";
import { Plugin } from "@tiptap/pm/state";
import { Decoration, DecorationSet, type EditorView } from "@tiptap/pm/view";
import {
  EMPTY,
  type ReviewMeta,
  type ReviewState,
  nextByPosition,
  pluginKey,
  rangeText,
  reviewState,
  setCurrentItem,
  setReviewView,
  stepReview,
  toggleReviewView,
} from "./reviewKinds/core";

// Re-exported so callers and tests keep their import path.
export {
  editsKind,
  LINE_EDIT_CURRENT_CLASS,
  LINE_EDIT_CLASS,
  acceptAllLineEdits,
  acceptCurrentLineEdit,
  acceptLineEdit,
  currentLineEdit,
  installLineEdits,
  lineEditState,
  rejectAllLineEdits,
  rejectCurrentLineEdit,
  rejectLineEdit,
  setCurrentLineEdit,
  stepLineEdit,
  type LineEditCallbacks,
  type LineEditState,
  type LineEditSuggestion,
} from "./reviewKinds/edits";
export {
  installFlags,
  keepReviewItem,
  liveItem,
  rejectAllFlags,
  setReviewView,
  toggleReviewView,
  type ReviewView,
} from "./reviewKinds/core";
export {
  LINE_NOTE_CURRENT_CLASS,
  LINE_NOTE_QUOTE_CLASS,
  currentLineNote,
  dismissAllLineNotes,
  dismissCurrentLineNote,
  dismissLineNote,
  installLineNotes,
  lineNoteState,
  stepLineNote,
  type LineNoteLinks,
  type LineNoteState,
  type LineNoteSuggestion,
} from "./reviewKinds/notes";

// The margin card's geometry (#2478): it starts CARD_OVERLAP_PX inside the prose
// column's right padding (which holds no text) and keeps CARD_GAP_PX clear of the
// frame's edge. Its width adapts to the room right of the column, between
// CARD_MIN_PX and CARD_MAX_PX; below the minimum it falls back to the block card
// under the paragraph.
const CARD_MIN_PX = 180;
const CARD_MAX_PX = 232;
const CARD_OVERLAP_PX = 32;
const CARD_GAP_PX = 12;
const CARD_WIDTH_VAR = "--line-edit-card-w";
// The CSS reads the overlap from here too, so the offset and the width maths
// can't drift apart.
const CARD_OVERLAP_VAR = "--line-edit-card-overlap";

/** The margin card's width for `room` px right of the prose column, or null
 *  when even the minimum card doesn't fit (narrow layout). */
export function marginCardWidth(room: number): number | null {
  const width = room + CARD_OVERLAP_PX - CARD_GAP_PX;
  return width < CARD_MIN_PX ? null : Math.min(width, CARD_MAX_PX);
}

/** Margin card (wide) or block under the paragraph (narrow). */
export function setLineEditCardWide(view: EditorView, wide: boolean): void {
  if (wide === reviewState(view.state).wide) return;
  view.dispatch(view.state.tr.setMeta(pluginKey, { type: "layout", wide } satisfies ReviewMeta).setMeta("addToHistory", false));
}

/** Keep `wide` in step with the room right of the prose column: the frame
 *  resizing, or the column's own width changing, can flip it. The plugin view
 *  is created before TipTap attaches `view.dom` to the page, so the frame is
 *  looked up on each measure (the first one fires once the editor is laid out)
 *  and observed from the moment it is found. */
function observeCardRoom(view: EditorView): () => void {
  if (typeof ResizeObserver === "undefined") return () => {};
  let frame: HTMLElement | null = null;
  const observer = new ResizeObserver(() => {
    if (!frame) {
      frame = view.dom.closest<HTMLElement>(".editor-wrap");
      if (!frame) return;
      observer.observe(frame);
    }
    const room = frame.getBoundingClientRect().left + frame.clientWidth - view.dom.getBoundingClientRect().right;
    const width = marginCardWidth(room);
    if (width !== null) {
      view.dom.style.setProperty(CARD_WIDTH_VAR, `${width}px`);
      view.dom.style.setProperty(CARD_OVERLAP_VAR, `${CARD_OVERLAP_PX}px`);
    }
    setLineEditCardWide(view, width !== null);
  });
  observer.observe(view.dom);
  return () => observer.disconnect();
}

export const LineEditSuggestions = Extension.create({
  name: "lineEditSuggestions",

  addProseMirrorPlugins() {
    let nextId = 1;
    return [
      new Plugin<ReviewState>({
        key: pluginKey,
        state: {
          init: () => EMPTY,
          apply: (tr, old, _oldState, newState) => {
            const meta = tr.getMeta(pluginKey) as ReviewMeta | undefined;
            if (meta?.type === "layout") return { ...old, wide: meta.wide };
            if (meta?.type === "install") {
              // By position: stepping walks the list, and a mixed review (ADR-0100)
              // arrives one kind after the other.
              const items = [...meta.items].sort((a, b) => a.from - b.from).map((e) => ({ ...e, id: nextId++ }));
              return { items, accepted: 0, kept: 0, currentId: nextByPosition(items, 0), wide: old.wide, view: "both" };
            }
            if (old.items.length === 0) return old;
            if (meta?.type === "view") return { ...old, view: meta.view };
            let items = old.items;
            if (tr.docChanged) {
              items = items.flatMap((item) => {
                const from = tr.mapping.map(item.from, 1);
                const to = tr.mapping.map(item.to, -1);
                // Deleted, or edited inside: the model's quote no longer holds.
                if (to <= from || rangeText(newState, from, to) !== item.kind.quoted(item)) return [];
                return [{ ...item, from, to }];
              });
            }
            let { accepted, kept } = old;
            let currentId = meta?.type === "current" ? meta.id : old.currentId;
            if (meta?.type === "resolve") {
              // Counted from the old list: an accepted edit's own range no longer
              // holds its quote, so the mapping above already dropped it.
              const resolved = old.items.filter((e) => meta.ids.includes(e.id)).length;
              items = items.filter((e) => !meta.ids.includes(e.id));
              if (meta.outcome === "accepted") accepted += resolved;
              if (meta.outcome === "kept") kept += resolved;
            }
            if (!items.some((e) => e.id === currentId)) {
              // The current item went (resolved, or dropped by typing): the next
              // one by position from where it was becomes current.
              const was = old.items.find((e) => e.id === old.currentId);
              currentId = nextByPosition(items, was ? tr.mapping.map(was.from, 1) : 0);
            }
            return { items, accepted, kept, currentId, wide: old.wide, view: old.view };
          },
        },
        view: (view) => ({ destroy: observeCardRoom(view) }),
        props: {
          // A click on an item's quoted text selects it (the edit's new-text
          // widget handles its own mousedown).
          handleClick: (view, _pos, event) => {
            const { items } = reviewState(view.state);
            const target = event.target as HTMLElement | null;
            for (const attr of new Set(items.map((i) => i.kind.idAttr))) {
              const id = Number(target?.closest?.(`[${attr}]`)?.getAttribute(attr));
              if (id > 0) {
                setCurrentItem(view, id);
                break;
              }
            }
            return false;
          },
          // Alt+Down / Alt+Up step, Alt+Enter accepts (edits only), Alt+Backspace
          // rejects / dismisses the current item, Alt+A / S / B pick the version
          // read - only while a review is open, so the keys are free otherwise.
          handleKeyDown: (view, event) => {
            const { items, currentId } = reviewState(view.state);
            if (items.length === 0) return false;
            const cur = items.find((i) => i.id === currentId);
            if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return false;
            // A / S / B read the passages as the page's words, the proposed ones, or
            // both. `code` first: on macOS Alt+letter yields a different `key`.
            const letter = /^Key[ASB]$/.test(event.code) ? event.code.slice(3) : event.key.toUpperCase();
            const act =
              letter === "A" ? () => toggleReviewView("now", view)
              : letter === "S" ? () => toggleReviewView("proposed", view)
              : letter === "B" ? () => setReviewView("both", view)
              : event.key === "ArrowDown" ? () => stepReview(view, 1)
              : event.key === "ArrowUp" ? () => stepReview(view, -1)
              : event.key === "Enter" && cur?.kind.accept ? () => cur.kind.accept?.(view)
              : event.key === "Backspace" && cur ? () => cur.kind.reject(view)
              : null;
            if (!act) return false;
            event.preventDefault();
            act();
            return true;
          },
          // The version being read, as a class on the editor root for review.css.
          attributes: (state): Record<string, string> => {
            const { items, view } = reviewState(state);
            return items.length > 0 && view !== "both" ? { class: `review-view-${view}` } : {};
          },
          decorations: (state) => {
            const { items, currentId, wide } = reviewState(state);
            if (items.length === 0) return DecorationSet.empty;
            const decos: Decoration[] = [];
            for (const item of items) decos.push(...item.kind.decorate(item, item.id === currentId));
            const cur = items.find((e) => e.id === currentId);
            if (cur) {
              // Wide: at the item, so the margin card shares its line. Narrow: at the
              // end of the paragraph, so the block card sits below it. Side 2 keeps it
              // after the new-text widget at the same position. A table cell is
              // position: relative, so a margin card there would anchor to the cell
              // and cover it: an item inside a table always gets the block card.
              const $to = state.doc.resolve(cur.to);
              const inCell = Array.from({ length: $to.depth + 1 }, (_, d) => $to.node(d)).some(
                (node) => node.type.spec.tableRole === "cell" || node.type.spec.tableRole === "header_cell",
              );
              const margin = wide && !inCell;
              const at = margin ? cur.to : $to.end();
              decos.push(
                Decoration.widget(at, (view) => cur.kind.card(cur, margin, view), {
                  side: 2,
                  key: `line-edit-card-${cur.kind.name}-${cur.id}-${at}-${margin}-${cur.kind.cardKey(cur)}`,
                  stopEvent: () => true,
                }),
              );
            }
            return DecorationSet.create(state.doc, decos);
          },
        },
      }),
    ];
  },
});
