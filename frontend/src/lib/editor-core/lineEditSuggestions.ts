/** Reviewing a model's line edits in place (#2460).
 *
 *  The placed edits live in this plugin's state, NOT in the document: the
 *  original text stays untouched until an edit is accepted. Each edit shows as
 *  its old text struck through (muted) and the new text right after it,
 *  underlined; no buttons in the text. One edit is the CURRENT one (stronger
 *  tint): clicking an edit selects it, and its decision card (lineEditCard.ts) /
 *  the Alt-keys step through them and accept or reject the current one. Positions are mapped
 *  through every transaction, and an edit is dropped once the writer edits
 *  inside it (its range no longer holds the text the model quoted). */
import { Extension } from "@tiptap/core";
import type { EditorState } from "@tiptap/pm/state";
import { Plugin, PluginKey, TextSelection } from "@tiptap/pm/state";
import { Decoration, DecorationSet, type EditorView } from "@tiptap/pm/view";
import type { PlacedEdit } from "./lineEdits";
import { buildLineEditCard } from "./lineEditCard";

export type LineEditSuggestion = PlacedEdit & { id: number };

export type LineEditState = {
  edits: LineEditSuggestion[];
  /** How many edits were accepted since the list was installed. */
  accepted: number;
  /** The edit the review bar and keys act on; null only when `edits` is empty. */
  currentId: number | null;
  /** Room for the decision card in the margin right of the prose column (set by
   *  the layout observer); else it is a block under the paragraph. */
  wide: boolean;
};

// Margin the card needs between the prose column's right edge and the frame's.
const CARD_ROOM_PX = 212;

type LineEditMeta =
  | { type: "install"; edits: PlacedEdit[] }
  | { type: "resolve"; ids: number[]; accepted: boolean }
  | { type: "current"; id: number }
  | { type: "layout"; wide: boolean };

export const LINE_EDIT_OLD_CLASS = "line-edit-old";
export const LINE_EDIT_NEW_CLASS = "line-edit-new";
export const LINE_EDIT_CURRENT_CLASS = "line-edit-current";

const pluginKey = new PluginKey<LineEditState>("line-edit-suggestions");
const EMPTY: LineEditState = { edits: [], accepted: 0, currentId: null, wide: false };

// Text of a range the way `find` was matched: leaves as the placement sentinel.
const rangeText = (state: EditorState, from: number, to: number) => state.doc.textBetween(from, to, "\n", "￼");

// The edit at or after `pos` by position, wrapping to the first.
function nextByPosition(edits: LineEditSuggestion[], pos: number): number | null {
  return (edits.find((e) => e.from >= pos) ?? edits[0])?.id ?? null;
}

export function lineEditState(state: EditorState): LineEditState {
  return pluginKey.getState(state) ?? EMPTY;
}

/** The current edit, or undefined when none is pending. */
export function currentLineEdit(state: EditorState): LineEditSuggestion | undefined {
  const { edits, currentId } = lineEditState(state);
  return edits.find((e) => e.id === currentId);
}

/** Margin card (wide) or block under the paragraph (narrow). */
export function setLineEditCardWide(view: EditorView, wide: boolean): void {
  if (wide === lineEditState(view.state).wide) return;
  view.dispatch(view.state.tr.setMeta(pluginKey, { type: "layout", wide } satisfies LineEditMeta).setMeta("addToHistory", false));
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
    setLineEditCardWide(view, room >= CARD_ROOM_PX);
  });
  observer.observe(view.dom);
  return () => observer.disconnect();
}

/** `collapseTo`: put the caret there (the end of the revised range), so the
 *  selection highlight doesn't sit over the passage under review. No scroll. */
export function installLineEdits(view: EditorView, edits: PlacedEdit[], collapseTo?: number): void {
  const tr = view.state.tr.setMeta(pluginKey, { type: "install", edits } satisfies LineEditMeta);
  if (collapseTo !== undefined) {
    tr.setSelection(TextSelection.near(tr.doc.resolve(Math.min(collapseTo, tr.doc.content.size))));
  }
  view.dispatch(tr);
}

function resolve(view: EditorView, ids: number[], accepted: boolean): void {
  const { edits } = lineEditState(view.state);
  const targets = edits.filter((e) => ids.includes(e.id));
  if (targets.length === 0) return;
  const tr = view.state.tr;
  if (accepted) {
    // Descending, so each replace leaves the positions of the ones before it intact.
    // The new text takes the marks of the replaced range, not the stored marks.
    for (const edit of [...targets].sort((a, b) => b.from - a.from)) {
      if (!edit.replace) {
        tr.delete(edit.from, edit.to);
        continue;
      }
      const $from = tr.doc.resolve(edit.from);
      const marks = $from.marksAcross(tr.doc.resolve(edit.to)) ?? $from.marks();
      tr.replaceWith(edit.from, edit.to, view.state.schema.text(edit.replace, marks));
    }
  }
  tr.setMeta(pluginKey, { type: "resolve", ids, accepted } satisfies LineEditMeta);
  view.dispatch(tr);
}

/** Bring the current edit itself into view (not its paragraph - a tall one could
 *  leave the edit off screen) without moving the caret or taking focus. */
function revealCurrent(view: EditorView): void {
  const edit = currentLineEdit(view.state);
  if (!edit) return;
  const span = view.dom.querySelector<HTMLElement>(`[data-line-edit-id="${edit.id}"]`);
  if (span?.scrollIntoView) {
    span.scrollIntoView({ block: "nearest", inline: "nearest" });
    return;
  }
  // No decorated span in the DOM: scroll the frame by the edit's coordinates.
  try {
    const scroller = view.dom.closest<HTMLElement>(".editor-wrap");
    if (!scroller) return;
    const box = scroller.getBoundingClientRect();
    const at = view.coordsAtPos(edit.from);
    if (at.top < box.top) scroller.scrollTop += at.top - box.top;
    else if (at.bottom > box.bottom) scroller.scrollTop += at.bottom - box.bottom;
  } catch {
    /* a position outside the rendered doc: nothing to reveal */
  }
}

export function setCurrentLineEdit(view: EditorView, id: number): void {
  const { edits, currentId } = lineEditState(view.state);
  if (currentId === id || !edits.some((e) => e.id === id)) return;
  view.dispatch(view.state.tr.setMeta(pluginKey, { type: "current", id } satisfies LineEditMeta));
}

/** Make the next (+1) or previous (-1) edit by position current, wrapping, and scroll to it. */
export function stepLineEdit(view: EditorView, dir: 1 | -1): void {
  const { edits, currentId } = lineEditState(view.state);
  if (edits.length === 0) return;
  const at = edits.findIndex((e) => e.id === currentId);
  setCurrentLineEdit(view, edits[(at + dir + edits.length) % edits.length].id);
  revealCurrent(view);
}

export function acceptCurrentLineEdit(view: EditorView): void {
  const { currentId } = lineEditState(view.state);
  if (currentId === null) return;
  resolve(view, [currentId], true);
  revealCurrent(view);
}

export function rejectCurrentLineEdit(view: EditorView): void {
  const { currentId } = lineEditState(view.state);
  if (currentId === null) return;
  resolve(view, [currentId], false);
  revealCurrent(view);
}

export const acceptLineEdit = (view: EditorView, id: number) => resolve(view, [id], true);
export const rejectLineEdit = (view: EditorView, id: number) => resolve(view, [id], false);
export const acceptAllLineEdits = (view: EditorView) =>
  resolve(view, lineEditState(view.state).edits.map((e) => e.id), true);
export const rejectAllLineEdits = (view: EditorView) =>
  resolve(view, lineEditState(view.state).edits.map((e) => e.id), false);

function widgetFor(view: EditorView, edit: LineEditSuggestion, current: boolean): HTMLElement {
  const added = document.createElement("span");
  added.className = current ? `${LINE_EDIT_NEW_CLASS} ${LINE_EDIT_CURRENT_CLASS}` : LINE_EDIT_NEW_CLASS;
  added.contentEditable = "false";
  added.title = edit.reason;
  added.textContent = edit.replace;
  // mousedown + preventDefault: selecting never blurs the editor.
  added.addEventListener("mousedown", (e) => {
    e.preventDefault();
    setCurrentLineEdit(view, edit.id);
  });
  return added;
}

export const LineEditSuggestions = Extension.create({
  name: "lineEditSuggestions",

  addProseMirrorPlugins() {
    let nextId = 1;
    return [
      new Plugin<LineEditState>({
        key: pluginKey,
        state: {
          init: () => EMPTY,
          apply: (tr, old, _oldState, newState) => {
            const meta = tr.getMeta(pluginKey) as LineEditMeta | undefined;
            if (meta?.type === "layout") return { ...old, wide: meta.wide };
            if (meta?.type === "install") {
              const edits = meta.edits.map((e) => ({ ...e, id: nextId++ }));
              return { edits, accepted: 0, currentId: nextByPosition(edits, 0), wide: old.wide };
            }
            if (old.edits.length === 0) return old;
            let edits = old.edits;
            if (tr.docChanged) {
              edits = edits.flatMap((edit) => {
                const from = tr.mapping.map(edit.from, 1);
                const to = tr.mapping.map(edit.to, -1);
                // Deleted, or edited inside: the model's quote no longer holds.
                if (to <= from || rangeText(newState, from, to) !== edit.find) return [];
                return [{ ...edit, from, to }];
              });
            }
            let accepted = old.accepted;
            let currentId = meta?.type === "current" ? meta.id : old.currentId;
            if (meta?.type === "resolve") {
              edits = edits.filter((e) => !meta.ids.includes(e.id));
              if (meta.accepted) accepted += meta.ids.length;
            }
            if (!edits.some((e) => e.id === currentId)) {
              // The current edit went (resolved, or dropped by typing): the next
              // one by position from where it was becomes current.
              const was = old.edits.find((e) => e.id === old.currentId);
              currentId = nextByPosition(edits, was ? tr.mapping.map(was.from, 1) : 0);
            }
            return { edits, accepted, currentId, wide: old.wide };
          },
        },
        view: (view) => ({ destroy: observeCardRoom(view) }),
        props: {
          // A click on the struck-through old text selects that edit (the new
          // text's widget handles its own mousedown).
          handleClick: (view, _pos, event) => {
            const target = event.target as HTMLElement | null;
            const id = Number(target?.closest?.("[data-line-edit-id]")?.getAttribute("data-line-edit-id"));
            if (id > 0) setCurrentLineEdit(view, id);
            return false;
          },
          // Alt+Down / Alt+Up step, Alt+Enter accepts, Alt+Backspace rejects the
          // current edit - only while edits are pending, so the keys are free otherwise.
          handleKeyDown: (view, event) => {
            if (lineEditState(view.state).edits.length === 0) return false;
            if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return false;
            const act =
              event.key === "ArrowDown" ? () => stepLineEdit(view, 1)
              : event.key === "ArrowUp" ? () => stepLineEdit(view, -1)
              : event.key === "Enter" ? () => acceptCurrentLineEdit(view)
              : event.key === "Backspace" ? () => rejectCurrentLineEdit(view)
              : null;
            if (!act) return false;
            event.preventDefault();
            act();
            return true;
          },
          decorations: (state) => {
            const { edits, currentId, wide } = lineEditState(state);
            if (edits.length === 0) return DecorationSet.empty;
            const decos: Decoration[] = [];
            for (const edit of edits) {
              const current = edit.id === currentId;
              decos.push(
                Decoration.inline(edit.from, edit.to, {
                  class: current ? `${LINE_EDIT_OLD_CLASS} ${LINE_EDIT_CURRENT_CLASS}` : LINE_EDIT_OLD_CLASS,
                  title: edit.reason,
                  "data-line-edit-id": String(edit.id),
                }),
              );
              if (!edit.replace) continue;
              decos.push(
                Decoration.widget(edit.to, (view) => widgetFor(view, edit, current), {
                  side: 1,
                  key: `line-edit-${edit.id}-${edit.to}-${edit.replace}-${current}`,
                  stopEvent: () => true,
                }),
              );
            }
            const cur = edits.find((e) => e.id === currentId);
            if (cur) {
              // Wide: at the edit, so the margin card shares its line. Narrow: at the
              // end of the paragraph, so the block card sits below it. Side 2 keeps it
              // after the new-text widget at the same position. A table cell is
              // position: relative, so a margin card there would anchor to the cell
              // and cover it: an edit inside a table always gets the block card.
              const $to = state.doc.resolve(cur.to);
              const inCell = Array.from({ length: $to.depth + 1 }, (_, d) => $to.node(d)).some(
                (node) => node.type.spec.tableRole === "cell" || node.type.spec.tableRole === "header_cell",
              );
              const margin = wide && !inCell;
              const at = margin ? cur.to : $to.end();
              decos.push(
                Decoration.widget(
                  at,
                  (view) =>
                    buildLineEditCard(cur.reason, margin, {
                      prev: () => stepLineEdit(view, -1),
                      next: () => stepLineEdit(view, 1),
                      accept: () => acceptCurrentLineEdit(view),
                      reject: () => rejectCurrentLineEdit(view),
                    }),
                  { side: 2, key: `line-edit-card-${cur.id}-${at}-${margin}-${cur.reason}`, stopEvent: () => true },
                ),
              );
            }
            return DecorationSet.create(state.doc, decos);
          },
        },
      }),
    ];
  },
});
