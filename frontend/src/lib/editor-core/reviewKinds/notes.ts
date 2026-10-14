/** The review kind for a lore check's notes (ADR-0098): each note underlines its
 *  quoted passage quietly (no strike-through, no proposed text); the card names
 *  the problem and the entry. Nothing here ever writes to the document - a note
 *  is read, opened or dismissed, and goes away once its quote is edited. */
import type { EditorState } from "@tiptap/pm/state";
import { Decoration, type EditorView } from "@tiptap/pm/view";
import type { PlacedNote } from "../lineEdits";
import { buildLineNoteCard } from "../lineNoteCard";
import {
  type ReviewKind,
  type ReviewMeta,
  installReview,
  pluginKey,
  reviewState,
  revealCurrent,
  stepReview,
} from "./core";

export type LineNoteSuggestion = PlacedNote & { id: number };

export type LineNoteState = {
  notes: LineNoteSuggestion[];
  /** The note the review bar and keys act on; null only when `notes` is empty. */
  currentId: number | null;
  wide: boolean;
};

/** What the run lends the review: opening the contradicted entry, and its name. */
export type LineNoteLinks = {
  openEntry: (id: string) => void;
  entryName: (id: string) => string;
};

export const LINE_NOTE_QUOTE_CLASS = "line-note-quote";
export const LINE_NOTE_CURRENT_CLASS = "line-note-current";

const asNote = (item: unknown) => item as LineNoteSuggestion;

/** A kind bound to one run's links. */
export function notesKind(links: LineNoteLinks): ReviewKind {
  const nameOf = (note: LineNoteSuggestion) => links.entryName(note.entry) || note.entry;
  return {
    name: "notes",
    idAttr: "data-line-note-id",
    quoted: (item) => asNote(item).quote,
    // Overlapping notes simply stack their decorations.
    decorate: (item, current) => [
      Decoration.inline(item.from, item.to, {
        class: current ? `${LINE_NOTE_QUOTE_CLASS} ${LINE_NOTE_CURRENT_CLASS}` : LINE_NOTE_QUOTE_CLASS,
        title: asNote(item).problem,
        "data-line-note-id": String(item.id),
      }),
    ],
    card: (item, margin, view) => {
      const note = asNote(item);
      return buildLineNoteCard(note.problem, nameOf(note), margin, {
        prev: () => stepLineNote(view, -1),
        next: () => stepLineNote(view, 1),
        openEntry: () => links.openEntry(note.entry),
        dismiss: () => dismissCurrentLineNote(view),
      });
    },
    cardKey: (item) => `${asNote(item).problem}-${nameOf(asNote(item))}`,
    // No `accept`: Alt+Enter does nothing for a note.
    reject: (view) => dismissCurrentLineNote(view),
  };
}

/** The open note list, or an empty one when the open review is not notes. */
export function lineNoteState(state: EditorState): LineNoteState {
  const s = reviewState(state);
  if (s.review?.name !== "notes") return { notes: [], currentId: null, wide: s.wide };
  return { notes: s.items as LineNoteSuggestion[], currentId: s.currentId, wide: s.wide };
}

export function currentLineNote(state: EditorState): LineNoteSuggestion | undefined {
  const { notes, currentId } = lineNoteState(state);
  return notes.find((n) => n.id === currentId);
}

/** `collapseTo`: the caret goes there (the end of the checked range). */
export function installLineNotes(
  view: EditorView,
  notes: PlacedNote[],
  collapseTo: number | undefined,
  links: LineNoteLinks,
): void {
  installReview(view, notesKind(links), notes, collapseTo);
}

/** Make the next (+1) or previous (-1) note by position current, wrapping. */
export function stepLineNote(view: EditorView, dir: 1 | -1): void {
  if (reviewState(view.state).review?.name === "notes") stepReview(view, dir);
}

function dismiss(view: EditorView, ids: number[]): void {
  if (ids.length === 0) return;
  view.dispatch(view.state.tr.setMeta(pluginKey, { type: "resolve", ids, accepted: false } satisfies ReviewMeta));
}

export function dismissCurrentLineNote(view: EditorView): void {
  const { currentId } = lineNoteState(view.state);
  if (currentId === null) return;
  dismiss(view, [currentId]);
  revealCurrent(view);
}

export const dismissLineNote = (view: EditorView, id: number) => dismiss(view, [id]);
export const dismissAllLineNotes = (view: EditorView) =>
  dismiss(view, lineNoteState(view.state).notes.map((n) => n.id));
