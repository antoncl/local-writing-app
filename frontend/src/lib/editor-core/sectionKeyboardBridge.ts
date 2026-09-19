// Body Sections keyboard bridge (#2009): ArrowUp/Left at the top of one
// section's editor (or ArrowDown/Right at its bottom) moves the caret into the
// neighbouring section instead of doing nothing — so the stack of TipTap
// editors (the free body + one per long_text section) reads like one
// continuous document to the keyboard. Backspace at a section start is
// deliberately NOT bridged (leave the default no-op): merging two independent
// metadata fields by deleting across their boundary would be a data-loss trap
// a plain caret move never risks.
import { TextSelection, type EditorState } from "@tiptap/pm/state";
import type { Editor } from "@tiptap/core";
import type { EditorView } from "@tiptap/pm/view";

export type SectionEdge = "start" | "end";

/** The two functions a section's editor can hand off the caret to — resolved
 *  lazily (called only once an arrow press actually bridges), so the caller
 *  never has to worry about a neighbour registering after this was captured. */
export type SectionNeighbours = { prev: (() => void) | null; next: (() => void) | null };

/** Pure: given the arrow key pressed and where the caret sits, which
 *  neighbour (if any) the bridge hands off to. A non-empty selection never
 *  bridges — extending/replacing a selection across a section boundary would
 *  be surprising, so the caret has to be collapsed first. */
export function sectionArrowDecision(input: {
  key: string;
  atDocStart: boolean;
  atDocEnd: boolean;
  onFirstLine: boolean;
  onLastLine: boolean;
  hasSelection: boolean;
}): "prev" | "next" | null {
  if (input.hasSelection) return null;
  if (input.key === "ArrowLeft" && input.atDocStart) return "prev";
  if (input.key === "ArrowUp" && input.onFirstLine) return "prev";
  if (input.key === "ArrowRight" && input.atDocEnd) return "next";
  if (input.key === "ArrowDown" && input.onLastLine) return "next";
  return null;
}

const ARROW_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"]);

/** Whether the caret's textblock is the FIRST (`"start"`) or LAST (`"end"`)
 *  textblock of the document. `view.endOfTextblock` only knows the edge of
 *  the caret's own paragraph; without this the bridge would fire from the
 *  last line of paragraph one and skip every paragraph below it. Pure over
 *  the editor state — no layout needed. */
export function inEdgeTextblock(state: EditorState, edge: SectionEdge): boolean {
  const { $from } = state.selection;
  if (!$from.parent.isTextblock) return false;
  const caretBlockStart = $from.start();
  let edgeBlockStart: number | null = null;
  state.doc.descendants((node, pos) => {
    if (!node.isTextblock) return true;
    const start = pos + 1;
    if (edge === "start") {
      if (edgeBlockStart === null) edgeBlockStart = start;
      return false;
    }
    edgeBlockStart = start;
    return false;
  });
  return edgeBlockStart === caretBlockStart;
}

/** The ProseMirror `handleKeyDown` check: computes `sectionArrowDecision`'s
 *  inputs off the live view and, when it fires AND the target neighbour is
 *  actually wired, hands off the caret and reports the key as handled (so the
 *  editor's own caret-move keymap never also runs). A held modifier (Shift —
 *  which would extend a selection — Ctrl/Cmd/Alt) always declines, before the
 *  doc-edge/first-line checks even run. */
export function handleSectionArrow(view: EditorView, event: KeyboardEvent, neighbours: SectionNeighbours): boolean {
  if (!ARROW_KEYS.has(event.key)) return false;
  if (event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return false;
  const { state } = view;
  const { $from, empty } = state.selection;
  const decision = sectionArrowDecision({
    key: event.key,
    atDocStart: $from.pos <= 1,
    atDocEnd: $from.pos >= state.doc.content.size - 1,
    onFirstLine: inEdgeTextblock(state, "start") && view.endOfTextblock("up"),
    onLastLine: inEdgeTextblock(state, "end") && view.endOfTextblock("down"),
    hasSelection: !empty,
  });
  const target = decision === "prev" ? neighbours.prev : decision === "next" ? neighbours.next : null;
  if (!target) return false;
  event.preventDefault();
  target();
  return true;
}

/** Put the caret at the very start of `editor`'s document and focus it. */
export function focusStart(editor: Editor): void {
  const tr = editor.state.tr.setSelection(TextSelection.atStart(editor.state.doc));
  editor.view.dispatch(tr);
  editor.commands.focus();
}

/** Put the caret at the very end of `editor`'s document and focus it. */
export function focusEnd(editor: Editor): void {
  const tr = editor.state.tr.setSelection(TextSelection.atEnd(editor.state.doc));
  editor.view.dispatch(tr);
  editor.commands.focus();
}

export type SectionRegistry = {
  /** Register the editor mounted at document position `index` — 0 is the
   *  free body, 1.. each long_text section in schema order. `fieldId` is the
   *  section's field id (null for the free body, which is never a "go to"
   *  target) — kept alongside the index so a section can be focused directly
   *  by field id (the rail's index-row "Go to …" jump), independent of the
   *  arrow-bridge ordering. */
  register: (index: number, fieldId: string | null, editor: Editor) => void;
  /** Remove every entry (both maps) whose registered editor IS `editor` —
   *  by identity, not by index/field id. A teardown names the instance going
   *  away, never "whatever is at this slot": a fast remount can register the
   *  NEW instance at the same index/field before the OLD one's cleanup runs
   *  (React/Svelte don't guarantee mount-before-unmount ordering across a
   *  keyed swap), and an index-keyed delete there would evict the live
   *  editor's registration instead of the dead one's (observed live: right
   *  after a project was created, the arrow bridge and "Go to …" went dead
   *  until reload). A no-op when `editor` isn't registered. */
  unregister: (editor: Editor) => void;
  /** The neighbours of the editor at `index`, resolved from whatever is
   *  currently registered — safe to call before every neighbour exists yet,
   *  since callers invoke it lazily (at keypress time), never cache the
   *  result across a render. */
  neighboursFor: (index: number) => SectionNeighbours;
  /** Focus the start of the section registered for `fieldId`, if any. */
  focus: (fieldId: string) => void;
};

/** Keeps every mounted section editor in document order so the keyboard
 *  bridge can resolve "the next/previous one" — and, separately, by field id
 *  so the rail's index row can jump straight to one. A plain in-memory
 *  registry (no Svelte reactivity): every consumer calls `neighboursFor` /
 *  `focus` imperatively, at the moment it's needed, so registration order
 *  relative to rendering never matters. */
export function createSectionRegistry(): SectionRegistry {
  const byIndex = new Map<number, Editor>();
  const byField = new Map<string, Editor>();

  function register(index: number, fieldId: string | null, editor: Editor): void {
    byIndex.set(index, editor);
    if (fieldId) byField.set(fieldId, editor);
  }

  function unregister(editor: Editor): void {
    for (const [key, value] of byIndex) if (value === editor) byIndex.delete(key);
    for (const [key, value] of byField) if (value === editor) byField.delete(key);
  }

  function neighboursFor(index: number): SectionNeighbours {
    let before: number | null = null;
    let after: number | null = null;
    for (const candidate of byIndex.keys()) {
      if (candidate < index && (before === null || candidate > before)) before = candidate;
      if (candidate > index && (after === null || candidate < after)) after = candidate;
    }
    return {
      prev: before !== null ? () => focusEnd(byIndex.get(before as number)!) : null,
      next: after !== null ? () => focusStart(byIndex.get(after as number)!) : null,
    };
  }

  function focus(fieldId: string): void {
    const editor = byField.get(fieldId);
    if (editor) focusStart(editor);
  }

  return { register, unregister, neighboursFor, focus };
}
