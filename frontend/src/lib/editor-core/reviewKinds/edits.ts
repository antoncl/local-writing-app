/** The review kind for a model's line edits (#2460): each edit reads as a
 *  word-level diff (#2531) - the passage's words that go are warm, the
 *  replacement's words that come in sit beside them, cool; accepting writes the
 *  whole replacement, rejecting leaves the text alone. */
import { Fragment, Slice } from "@tiptap/pm/model";
import type { EditorState } from "@tiptap/pm/state";
import { Decoration, type EditorView } from "@tiptap/pm/view";
import type { DiffRun } from "@/lib/types";
import { olderFirst } from "@/lib/utils/diffRuns";
import { diffRuns } from "@/lib/utils/snapshotDiff";
import type { PlacedEdit } from "../lineEdits";
import { buildLineEditCard } from "../lineEditCard";
import {
  type ReviewKind,
  type ReviewMeta,
  type ReviewOutcome,
  installReview,
  liveItem,
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
  /** How many were kept as TODOs (ADR-0099), likewise. */
  kept: number;
  /** The edit the review bar and keys act on; null only when `edits` is empty. */
  currentId: number | null;
  wide: boolean;
};

export const LINE_EDIT_CLASS = "line-edit";
export const LINE_EDIT_CURRENT_CLASS = "line-edit-current";

/** The diff of one edit, memoized per (find, replace) so decorations do not
 *  re-diff on every transaction. Exported for the test that pins the memo. */
export const editRunsCache = new Map<string, DiffRun[]>();
const EDIT_RUNS_CACHE_MAX = 200;

function editRuns(find: string, replace: string): DiffRun[] {
  const key = `${find}\u0000${replace}`;
  let runs = editRunsCache.get(key);
  if (!runs) {
    // The replacement is the other version (cool), the passage the page's (warm).
    // The passage is the older text, so its going words come before the coming
    // ones ("on in", not "in on") — older text first (#2533).
    runs = olderFirst(diffRuns(replace, find), "now");
    // The offsets walk `find`, so its runs must spell it exactly. The engine is
    // markdown-aware; should it ever not reproduce the texts, mark the whole
    // passage and the whole replacement rather than drift onto the wrong words.
    const spells = (kind: "now" | "was") =>
      runs!.filter((r) => r.kind === "equal" || r.kind === kind).map((r) => r.text).join("");
    if (spells("now") !== find || spells("was") !== replace) {
      runs = [
        ...(find ? [{ kind: "now" as const, text: find, stacked: false }] : []),
        ...(replace ? [{ kind: "was" as const, text: replace, stacked: false }] : []),
      ];
    }
    if (editRunsCache.size >= EDIT_RUNS_CACHE_MAX) editRunsCache.clear();
    editRunsCache.set(key, runs);
  }
  return runs;
}

/** Words only the replacement has: they come in, so they sit as a cool widget. */
function widgetFor(view: EditorView, edit: LineEditSuggestion, text: string, current: boolean): HTMLElement {
  const added = document.createElement("span");
  // `line-edit-added`: the widget is a sibling of the passage's spans, not inside
  // `.line-edit`, so the version views (review.css) key on this class - and on
  // `-current`, so the current edit's new words share its tint in Proposed.
  added.className = current ? "r-was line-edit-added line-edit-added-current" : "r-was line-edit-added";
  added.contentEditable = "false";
  added.title = edit.reason;
  added.textContent = text;
  // mousedown + preventDefault: selecting never blurs the editor.
  added.addEventListener("mousedown", (e) => {
    e.preventDefault();
    setCurrentItem(view, edit.id);
  });
  return added;
}

/** What the run lends the review: keeping an edit as a TODO (ADR-0099). The
 *  edit is passed as the review holds it when the writer clicks. */
export type LineEditCallbacks = {
  keep: (view: EditorView, edit: LineEditSuggestion) => void;
};

/** A kind bound to one run's callbacks. */
export const editsKind = (callbacks: LineEditCallbacks): ReviewKind => ({
  name: "edits",
  idAttr: "data-line-edit-id",
  quoted: (item) => (item as LineEditSuggestion).find,
  decorate(item, current) {
    const edit = item as LineEditSuggestion;
    // The whole passage: click-to-select and the current-item outline.
    const decos = [
      Decoration.inline(edit.from, edit.to, {
        class: current ? `${LINE_EDIT_CLASS} ${LINE_EDIT_CURRENT_CLASS}` : LINE_EDIT_CLASS,
        title: edit.reason,
        "data-line-edit-id": String(edit.id),
      }),
    ];
    // Placement guarantees one textblock and no inline leaves, so an offset into
    // `find` is an offset into the doc.
    let o = 0;
    for (const run of editRuns(edit.find, edit.replace)) {
      if (run.kind === "equal") {
        o += run.text.length;
      } else if (run.kind === "now") {
        decos.push(Decoration.inline(edit.from + o, edit.from + o + run.text.length, { class: "r-now" }));
        o += run.text.length;
      } else {
        const text = run.text;
        decos.push(
          Decoration.widget(edit.from + o, (view) => widgetFor(view, edit, text, current), {
            side: 1,
            // `current` in the key: a widget whose class changes must be rebuilt.
            key: `line-edit-${edit.id}-${edit.from + o}-${text}-${current ? "c" : ""}`,
            stopEvent: () => true,
          }),
        );
      }
    }
    return decos;
  },
  card: (item, margin, view) =>
    buildLineEditCard((item as LineEditSuggestion).reason, margin, {
      prev: () => stepLineEdit(view, -1),
      next: () => stepLineEdit(view, 1),
      accept: () => acceptCurrentLineEdit(view),
      keep: () => {
        const edit = liveItem(view.state, item.id);
        if (edit) callbacks.keep(view, edit as unknown as LineEditSuggestion);
      },
      reject: () => rejectCurrentLineEdit(view),
    }),
  cardKey: (item) => (item as LineEditSuggestion).reason,
  accept: (view) => acceptCurrentLineEdit(view),
  reject: (view) => rejectCurrentLineEdit(view),
});

/** The edits of the open review (empty when it holds none). `currentId` is the
 *  current item only when that is an edit. */
export function lineEditState(state: EditorState): LineEditState {
  const s = reviewState(state);
  const edits = s.items.filter((i) => i.kind.name === "edits") as unknown as LineEditSuggestion[];
  const currentId = edits.some((e) => e.id === s.currentId) ? s.currentId : null;
  return { edits, accepted: s.accepted, kept: s.kept, currentId, wide: s.wide };
}

/** The current edit, or undefined when none is pending. */
export function currentLineEdit(state: EditorState): LineEditSuggestion | undefined {
  const { edits, currentId } = lineEditState(state);
  return edits.find((e) => e.id === currentId);
}

export const installLineEdits = (
  view: EditorView,
  edits: PlacedEdit[],
  collapseTo?: number,
  callbacks: LineEditCallbacks = { keep: () => {} },
): void => installReview(view, editsKind(callbacks), edits, collapseTo);

export const setCurrentLineEdit = setCurrentItem;

/** Make the next (+1) or previous (-1) item by position current, wrapping, and
 *  scroll to it - across both kinds when the review holds both. */
export const stepLineEdit = stepReview;

const BLANK_LINE = /\n[ \t]*\n/;

function resolve(view: EditorView, ids: number[], outcome: ReviewOutcome): void {
  const { edits } = lineEditState(view.state);
  const targets = edits.filter((e) => ids.includes(e.id));
  if (targets.length === 0) return;
  const tr = view.state.tr;
  if (outcome === "accepted") {
    // Descending, so each replace leaves the positions of the ones before it intact.
    // The new text takes the marks of the replaced range, not the stored marks.
    for (const edit of [...targets].sort((a, b) => b.from - a.from)) {
      if (!edit.replace) {
        tr.delete(edit.from, edit.to);
        continue;
      }
      const $from = tr.doc.resolve(edit.from);
      const marks = $from.marksAcross(tr.doc.resolve(edit.to)) ?? $from.marks();
      const { schema } = view.state;
      if (BLANK_LINE.test(edit.replace)) {
        // Paragraphs (ADR-0100 decision 6): an open slice merges the first part into
        // the passage's paragraph and the last with the text after it.
        const parts = edit.replace.split(BLANK_LINE).map((p) => p.replace(/^\n+|\n+$/g, "")).filter(Boolean);
        const paras = parts.map((p) => schema.nodes.paragraph.create(null, schema.text(p, marks)));
        // Only blank lines: nothing to insert, so it is a cut.
        if (paras.length === 0) tr.delete(edit.from, edit.to);
        else tr.replace(edit.from, edit.to, new Slice(Fragment.from(paras), 1, 1));
        continue;
      }
      tr.replaceWith(edit.from, edit.to, schema.text(edit.replace, marks));
    }
  }
  tr.setMeta(pluginKey, { type: "resolve", ids, outcome } satisfies ReviewMeta);
  view.dispatch(tr);
}

export function acceptCurrentLineEdit(view: EditorView): void {
  const { currentId } = lineEditState(view.state);
  if (currentId === null) return;
  resolve(view, [currentId], "accepted");
  revealCurrent(view);
}

export function rejectCurrentLineEdit(view: EditorView): void {
  const { currentId } = lineEditState(view.state);
  if (currentId === null) return;
  resolve(view, [currentId], "rejected");
  revealCurrent(view);
}

export const acceptLineEdit = (view: EditorView, id: number) => resolve(view, [id], "accepted");
export const rejectLineEdit = (view: EditorView, id: number) => resolve(view, [id], "rejected");
export const acceptAllLineEdits = (view: EditorView) =>
  resolve(view, lineEditState(view.state).edits.map((e) => e.id), "accepted");
export const rejectAllLineEdits = (view: EditorView) =>
  resolve(view, lineEditState(view.state).edits.map((e) => e.id), "rejected");
