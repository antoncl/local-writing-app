/** The review kind for a model's line edits (#2460): each edit shows its old text
 *  struck through (muted) and the new text right after it, underlined; accepting
 *  writes the replacement, rejecting leaves the text alone. */
import type { EditorState } from "@tiptap/pm/state";
import { Decoration, type EditorView } from "@tiptap/pm/view";
import type { PlacedEdit } from "../lineEdits";
import { buildLineEditCard } from "../lineEditCard";
import {
  type ReviewKind,
  type ReviewMeta,
  installReview,
  pluginKey,
  reviewState,
  revealCurrent,
  setCurrentItem,
  stepReview,
} from "./core";

export type LineEditSuggestion = PlacedEdit & { id: number };

export type LineEditState = {
  edits: LineEditSuggestion[];
  /** How many edits were accepted since the list was installed. */
  accepted: number;
  /** The edit the review bar and keys act on; null only when `edits` is empty. */
  currentId: number | null;
  wide: boolean;
};

export const LINE_EDIT_OLD_CLASS = "line-edit-old";
export const LINE_EDIT_NEW_CLASS = "line-edit-new";
export const LINE_EDIT_CURRENT_CLASS = "line-edit-current";

function widgetFor(view: EditorView, edit: LineEditSuggestion, current: boolean): HTMLElement {
  const added = document.createElement("span");
  added.className = current ? `${LINE_EDIT_NEW_CLASS} ${LINE_EDIT_CURRENT_CLASS}` : LINE_EDIT_NEW_CLASS;
  added.contentEditable = "false";
  added.title = edit.reason;
  added.textContent = edit.replace;
  // mousedown + preventDefault: selecting never blurs the editor.
  added.addEventListener("mousedown", (e) => {
    e.preventDefault();
    setCurrentItem(view, edit.id);
  });
  return added;
}

export const EDITS: ReviewKind = {
  name: "edits",
  idAttr: "data-line-edit-id",
  quoted: (item) => (item as LineEditSuggestion).find,
  decorate(item, current) {
    const edit = item as LineEditSuggestion;
    const decos = [
      Decoration.inline(edit.from, edit.to, {
        class: current ? `${LINE_EDIT_OLD_CLASS} ${LINE_EDIT_CURRENT_CLASS}` : LINE_EDIT_OLD_CLASS,
        title: edit.reason,
        "data-line-edit-id": String(edit.id),
      }),
    ];
    if (edit.replace) {
      decos.push(
        Decoration.widget(edit.to, (view) => widgetFor(view, edit, current), {
          side: 1,
          key: `line-edit-${edit.id}-${edit.to}-${edit.replace}-${current}`,
          stopEvent: () => true,
        }),
      );
    }
    return decos;
  },
  card: (item, margin, view) =>
    buildLineEditCard((item as LineEditSuggestion).reason, margin, {
      prev: () => stepLineEdit(view, -1),
      next: () => stepLineEdit(view, 1),
      accept: () => acceptCurrentLineEdit(view),
      reject: () => rejectCurrentLineEdit(view),
    }),
  cardKey: (item) => (item as LineEditSuggestion).reason,
  accept: (view) => acceptCurrentLineEdit(view),
  reject: (view) => rejectCurrentLineEdit(view),
};

/** The open edit list, or an empty one when the open review is not edits. */
export function lineEditState(state: EditorState): LineEditState {
  const s = reviewState(state);
  if (s.review?.name !== "edits") return { edits: [], accepted: 0, currentId: null, wide: s.wide };
  return { edits: s.items as LineEditSuggestion[], accepted: s.accepted, currentId: s.currentId, wide: s.wide };
}

/** The current edit, or undefined when none is pending. */
export function currentLineEdit(state: EditorState): LineEditSuggestion | undefined {
  const { edits, currentId } = lineEditState(state);
  return edits.find((e) => e.id === currentId);
}

export const installLineEdits = (view: EditorView, edits: PlacedEdit[], collapseTo?: number): void =>
  installReview(view, EDITS, edits, collapseTo);

export const setCurrentLineEdit = setCurrentItem;

/** Make the next (+1) or previous (-1) edit by position current, wrapping, and scroll to it. */
export function stepLineEdit(view: EditorView, dir: 1 | -1): void {
  if (reviewState(view.state).review?.name === "edits") stepReview(view, dir);
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
  tr.setMeta(pluginKey, { type: "resolve", ids, accepted } satisfies ReviewMeta);
  view.dispatch(tr);
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
