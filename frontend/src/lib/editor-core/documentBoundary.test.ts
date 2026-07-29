// #368: undo must not reach across a document switch. These tests drive the
// real prosemirror-history plugin on headless EditorState — no DOM, no TipTap
// mount (the component harness deliberately excludes TipTap; the boundary
// logic lives here precisely so it is testable without one).
import { describe, expect, it } from "vitest";
import { history, redo, undo, undoDepth } from "@tiptap/pm/history";
import { EditorState, type Transaction } from "@tiptap/pm/state";
import { schema } from "@tiptap/pm/schema-basic";

import { stateAtDocumentBoundary } from "./documentBoundary";

function stateWithHistory(): EditorState {
  return EditorState.create({ schema, plugins: [history()] });
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
