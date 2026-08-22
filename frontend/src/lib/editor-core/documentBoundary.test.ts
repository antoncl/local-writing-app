// #368: undo must not reach across a document switch. These tests drive the
// real prosemirror-history plugin on headless EditorState — no DOM, no TipTap
// mount (the component harness deliberately excludes TipTap; the boundary
// logic lives here precisely so it is testable without one).
import { describe, expect, it } from "vitest";
import { history, redo, undo, undoDepth } from "@tiptap/pm/history";
import { EditorState, type Transaction } from "@tiptap/pm/state";
import { schema } from "@tiptap/pm/schema-basic";

import { minimalReplaceTransaction, stateAtDocumentBoundary } from "./documentBoundary";

function stateWithHistory(): EditorState {
  return EditorState.create({ schema, plugins: [history()] });
}

/** Build a `doc` node with one paragraph per string. */
function docWithParagraphs(...texts: string[]) {
  return schema.node(
    "doc",
    null,
    texts.map((text) => schema.node("paragraph", null, [schema.text(text)])),
  );
}

/** The position right before paragraph `index`'s closing tag — where "append
 * to the end of this paragraph's text" lands. */
function paragraphTextEnd(doc: ReturnType<typeof docWithParagraphs>, index: number): number {
  let pos = 0;
  for (let i = 0; i < index; i++) pos += doc.child(i).nodeSize;
  return pos + doc.child(index).nodeSize - 1;
}

function type(state: EditorState, text: string): EditorState {
  return state.apply(state.tr.insertText(text, state.doc.content.size - 1));
}

/** Run a ProseMirror command function, returning the resulting state (or the
 * input state when the command reports it had nothing to do). */
function run(
  state: EditorState,
  command: (s: EditorState, d?: (tr: Transaction) => void) => boolean,
): { applied: boolean; state: EditorState } {
  let next = state;
  const applied = command(state, (tr) => {
    next = state.apply(tr);
  });
  return { applied, state: next };
}

describe("stateAtDocumentBoundary (#368)", () => {
  it("empties the undo stack while keeping the document", () => {
    let state = stateWithHistory();
    state = type(state, "document A");
    state = type(state, " more");
    expect(undoDepth(state)).toBeGreaterThan(0);

    const fresh = stateAtDocumentBoundary(state);
    expect(undoDepth(fresh)).toBe(0);
    expect(fresh.doc.eq(state.doc)).toBe(true);
    expect(fresh.plugins).toEqual(state.plugins);
  });

  it("undo after the boundary is a no-op — it cannot reach the previous document", () => {
    // Simulate the switch: type into doc A, replace content with doc B (the
    // ordinary transaction setContent produces), cross the boundary.
    let state = stateWithHistory();
    state = type(state, "scene A prose");
    const docB = schema.node("doc", null, [
      schema.node("paragraph", null, [schema.text("scene B prose")]),
    ]);
    state = state.apply(
      state.tr.replaceWith(0, state.doc.content.size, docB.content),
    );
    const fresh = stateAtDocumentBoundary(state);

    const undone = run(fresh, undo);
    expect(undone.applied).toBe(false);
    expect(undone.state.doc.textContent).toBe("scene B prose");
  });

  it("without the boundary, undo DOES resurrect the previous document (the bug)", () => {
    // The tripwire: if prosemirror-history ever stops threading history
    // through content replacement, the boundary reset becomes dead code and
    // this test says so.
    let state = stateWithHistory();
    state = type(state, "scene A prose");
    const docB = schema.node("doc", null, [
      schema.node("paragraph", null, [schema.text("scene B prose")]),
    ]);
    state = state.apply(
      state.tr.replaceWith(0, state.doc.content.size, docB.content),
    );

    const undone = run(state, undo);
    expect(undone.applied).toBe(true);
    expect(undone.state.doc.textContent).not.toBe("scene B prose");
  });

  it("edits after the boundary undo normally, and redo works, within the new document", () => {
    let state = stateWithHistory();
    state = type(state, "scene A");
    let fresh = stateAtDocumentBoundary(state);

    fresh = type(fresh, " and new words");
    expect(undoDepth(fresh)).toBeGreaterThan(0);

    const undone = run(fresh, undo);
    expect(undone.applied).toBe(true);
    expect(undone.state.doc.textContent).toBe("scene A");

    const redone = run(undone.state, redo);
    expect(redone.applied).toBe(true);
    expect(redone.state.doc.textContent).toBe("scene A and new words");
  });
});

describe("minimalReplaceTransaction (#694)", () => {
  it("returns null when the documents are already identical", () => {
    const docA = docWithParagraphs("one", "two", "three");
    const state = EditorState.create({ schema, doc: docA });
    const sameDoc = docWithParagraphs("one", "two", "three");

    expect(minimalReplaceTransaction(state, sameDoc)).toBeNull();
  });

  it("replaces only the changed range", () => {
    const docA = docWithParagraphs("one", "two", "three");
    const docB = docWithParagraphs("one", "two", "THREE changed");
    const state = EditorState.create({ schema, doc: docA });

    const tr = minimalReplaceTransaction(state, docB);
    expect(tr).not.toBeNull();
    const next = state.apply(tr!);
    expect(next.doc.eq(docB)).toBe(true);
  });

  it("undo trail survives a reconcile — the diff never lands on the undo stack, and undo reverts only the prior user edit", () => {
    const docA = docWithParagraphs("one", "two", "three");
    let state = EditorState.create({ schema, doc: docA, plugins: [history()] });

    // A user edit to paragraph ONE — a normal, undoable transaction.
    const p1End = paragraphTextEnd(state.doc, 0);
    state = state.apply(state.tr.insertText(" EDITED", p1End));
    expect(undoDepth(state)).toBe(1);

    // The reconcile: paragraph THREE changes server-side (e.g. a TODO toggle
    // strips a marker). Apply it the same way ProseBodyView does — a
    // minimal-diff transaction dispatched via a plain state.apply.
    const docB = docWithParagraphs("one EDITED", "two", "three RECONCILED");
    const tr = minimalReplaceTransaction(state, docB);
    expect(tr).not.toBeNull();
    state = state.apply(tr!);

    // The diff itself must NOT land on the undo stack.
    expect(undoDepth(state)).toBe(1);
    expect(state.doc.eq(docB)).toBe(true);

    // Undo reverts the paragraph-ONE edit; paragraph THREE's reconciled
    // change remains — the #694 guarantee that a TODO toggle no longer
    // discards the author's undo trail.
    const undone = run(state, undo);
    expect(undone.applied).toBe(true);
    expect(undone.state.doc.child(0).textContent).toBe("one");
    expect(undone.state.doc.child(2).textContent).toBe("three RECONCILED");
  });
});
