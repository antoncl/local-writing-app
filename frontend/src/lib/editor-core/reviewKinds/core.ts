/** The shared core of the in-editor review surface (#2460, ADR-0098 decision 5).
 *
 *  One ProseMirror plugin (lineEditSuggestions.ts) reviews a list of placed items
 *  in place; WHAT an item is - a line edit to accept or reject, a lore-check note
 *  to read and dismiss - is a `ReviewKind` the run installs with its items. The
 *  kind owns the per-handler parts (decorations, the decision card, which keys
 *  act, when an item is no longer valid); everything else - current item,
 *  stepping, position mapping, scrolling into view - is here, once. */
import type { EditorState, Transaction } from "@tiptap/pm/state";
import { PluginKey, TextSelection } from "@tiptap/pm/state";
import type { Decoration, EditorView } from "@tiptap/pm/view";

/** What every reviewed item is: an id and a range in the document. */
export type ReviewItem = { id: number; from: number; to: number };

export interface ReviewKind {
  readonly name: "edits" | "notes";
  /** The attribute marking an item's inline text, for clicks and reveal. */
  readonly idAttr: string;
  /** The text the item's range must still hold; a doc change that alters it
   *  drops the item (the model's quote no longer holds). */
  quoted(item: ReviewItem): string;
  /** The item's inline decoration and any widgets (the proposed text). */
  decorate(item: ReviewItem, current: boolean): Decoration[];
  /** The decision card for the current item. */
  card(item: ReviewItem, margin: boolean, view: EditorView): HTMLElement;
  /** What the card shows, so a changed card re-renders. */
  cardKey(item: ReviewItem): string;
  /** Alt+Enter. Absent when the review has nothing to accept. */
  accept?(view: EditorView): void;
  /** Alt+Backspace: reject (edits) or dismiss (notes) the current item. */
  reject(view: EditorView): void;
}

/** A stored item carries its kind, so one review can hold edits and notes
 *  together (ADR-0100 decision 5); the kind supplies its decoration, card, keys
 *  and validity check. */
export type ReviewEntry = ReviewItem & { kind: ReviewKind };

/** An item as a run hands it over, before it gets an id. */
export type FlagInput = Omit<ReviewItem, "id"> & { kind: ReviewKind };

export type ReviewState = {
  /** The open review's items; empty when no review is open. */
  items: ReviewEntry[];
  /** How many items were accepted since the list was installed. */
  accepted: number;
  /** How many were kept as TODOs (ADR-0099), likewise. */
  kept: number;
  /** The item the review bar and keys act on; null only when `items` is empty. */
  currentId: number | null;
  /** Room for the decision card in the margin right of the prose column (set by
   *  the layout observer); else it is a block under the paragraph. */
  wide: boolean;
};

/** How a flag was settled: taken, turned down, or turned into a TODO (ADR-0099). */
export type ReviewOutcome = "accepted" | "rejected" | "kept";

export type ReviewMeta =
  | { type: "install"; items: FlagInput[] }
  | { type: "resolve"; ids: number[]; outcome: ReviewOutcome }
  | { type: "current"; id: number }
  | { type: "layout"; wide: boolean };

export const pluginKey = new PluginKey<ReviewState>("line-edit-suggestions");
export const EMPTY: ReviewState = { items: [], accepted: 0, kept: 0, currentId: null, wide: false };

export const reviewState = (state: EditorState): ReviewState => pluginKey.getState(state) ?? EMPTY;

/** The current item, or undefined when none is pending. */
export function currentItem(state: EditorState): ReviewEntry | undefined {
  const { items, currentId } = reviewState(state);
  return items.find((i) => i.id === currentId);
}

/** Text of a range the way a quote was matched: leaves as the placement sentinel. */
export const rangeText = (state: EditorState, from: number, to: number) =>
  state.doc.textBetween(from, to, "\n", "￼");

/** The item with `id` as the open review holds it now (positions mapped). */
export const liveItem = (state: EditorState, id: number): ReviewEntry | undefined =>
  reviewState(state).items.find((i) => i.id === id);

/** Resolve one item as kept: its TODO is made, the document is not touched. */
export function keepReviewItem(view: EditorView, id: number): void {
  view.dispatch(view.state.tr.setMeta(pluginKey, { type: "resolve", ids: [id], outcome: "kept" } satisfies ReviewMeta));
  revealCurrent(view);
}

/** The item at or after `pos` by position, wrapping to the first. */
export function nextByPosition(items: ReviewItem[], pos: number): number | null {
  return (items.find((i) => i.from >= pos) ?? items[0])?.id ?? null;
}

/** Install `items`, all of one `review` kind. */
export function installReview(
  view: EditorView,
  review: ReviewKind,
  items: Omit<ReviewItem, "id">[],
  collapseTo?: number,
): void {
  installFlags(view, items.map((i) => ({ ...i, kind: review })), collapseTo);
}

/** Install a list whose items each carry their own kind (a mixed review).
 *  `collapseTo`: put the caret there (the end of the reviewed range), so the
 *  selection highlight doesn't sit over the passage under review. Then bring the
 *  first item and its card into view (#2478). */
export function installFlags(view: EditorView, items: FlagInput[], collapseTo?: number): void {
  const tr: Transaction = view.state.tr.setMeta(pluginKey, { type: "install", items } satisfies ReviewMeta);
  if (collapseTo !== undefined) {
    tr.setSelection(TextSelection.near(tr.doc.resolve(Math.min(collapseTo, tr.doc.content.size))));
  }
  view.dispatch(tr);
  // A run that asked for inputs left focus in its dialog: give it back, or the
  // review keys (Alt+Up/Down, ...) don't reach the editor and the browser keeps
  // showing the old selection over the passage.
  view.focus();
  revealCurrent(view);
}

/** Bring the current item AND its decision card into view (#2478) without moving
 *  the caret or taking focus. The item itself, not its paragraph (a tall one
 *  could leave the item off screen). When item and card don't both fit - a
 *  block card under a very tall paragraph - the item wins. */
export function revealCurrent(view: EditorView): void {
  const item = currentItem(view.state);
  if (!item) return;
  const span = view.dom.querySelector<HTMLElement>(`[${item.kind.idAttr}="${item.id}"]`);
  const scroller = view.dom.closest<HTMLElement>(".editor-wrap");
  if (!scroller) {
    span?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    return;
  }
  let top: number;
  let bottom: number;
  if (span) {
    ({ top, bottom } = span.getBoundingClientRect());
  } else {
    try {
      ({ top, bottom } = view.coordsAtPos(item.from));
    } catch {
      return; // a position outside the rendered doc: nothing to reveal
    }
  }
  const box = scroller.getBoundingClientRect();
  const card = view.dom.querySelector<HTMLElement>(".line-edit-card");
  if (card) {
    const c = card.getBoundingClientRect();
    const withCard = { top: Math.min(top, c.top), bottom: Math.max(bottom, c.bottom) };
    if (withCard.bottom - withCard.top <= box.height) ({ top, bottom } = withCard);
  }
  if (top < box.top) scroller.scrollTop += top - box.top;
  else if (bottom > box.bottom) scroller.scrollTop += bottom - box.bottom;
}

export function setCurrentItem(view: EditorView, id: number): void {
  const { items, currentId } = reviewState(view.state);
  if (currentId === id || !items.some((i) => i.id === id)) return;
  view.dispatch(view.state.tr.setMeta(pluginKey, { type: "current", id } satisfies ReviewMeta));
}

/** Make the next (+1) or previous (-1) item by position current, wrapping, and scroll to it. */
export function stepReview(view: EditorView, dir: 1 | -1): void {
  const { items, currentId } = reviewState(view.state);
  if (items.length === 0) return;
  const at = items.findIndex((i) => i.id === currentId);
  setCurrentItem(view, items[(at + dir + items.length) % items.length].id);
  revealCurrent(view);
}

/** Reject every item, whatever its kind: neither kind touches the document on reject. */
export function rejectAllFlags(view: EditorView): void {
  const ids = reviewState(view.state).items.map((i) => i.id);
  if (ids.length === 0) return;
  view.dispatch(view.state.tr.setMeta(pluginKey, { type: "resolve", ids, outcome: "rejected" } satisfies ReviewMeta));
}
