// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import type { EditorView } from "@tiptap/pm/view";
import {
  createSectionRegistry,
  handleSectionArrow,
  inEdgeTextblock,
  sectionArrowDecision,
  type SectionNeighbours,
} from "./sectionKeyboardBridge";
import { proseStarterKit } from "./proseStarterKit";

describe("sectionArrowDecision", () => {
  const base = {
    key: "ArrowDown",
    atDocStart: false,
    atDocEnd: false,
    onFirstLine: false,
    onLastLine: false,
    hasSelection: false,
  };

  it("ArrowUp on the first visual line bridges to prev", () => {
    expect(sectionArrowDecision({ ...base, key: "ArrowUp", onFirstLine: true })).toBe("prev");
  });
  it("ArrowUp NOT on the first line declines", () => {
    expect(sectionArrowDecision({ ...base, key: "ArrowUp", onFirstLine: false })).toBeNull();
  });
  it("ArrowLeft at doc start bridges to prev", () => {
    expect(sectionArrowDecision({ ...base, key: "ArrowLeft", atDocStart: true })).toBe("prev");
  });
  it("ArrowLeft NOT at doc start declines", () => {
    expect(sectionArrowDecision({ ...base, key: "ArrowLeft", atDocStart: false })).toBeNull();
  });
  it("ArrowDown on the last visual line bridges to next", () => {
    expect(sectionArrowDecision({ ...base, key: "ArrowDown", onLastLine: true })).toBe("next");
  });
  it("ArrowDown NOT on the last line declines", () => {
    expect(sectionArrowDecision({ ...base, key: "ArrowDown", onLastLine: false })).toBeNull();
  });
  it("ArrowRight at doc end bridges to next", () => {
    expect(sectionArrowDecision({ ...base, key: "ArrowRight", atDocEnd: true })).toBe("next");
  });
  it("ArrowRight NOT at doc end declines", () => {
    expect(sectionArrowDecision({ ...base, key: "ArrowRight", atDocEnd: false })).toBeNull();
  });
  it("a non-empty selection always declines, even at a bridging edge", () => {
    expect(sectionArrowDecision({ ...base, key: "ArrowLeft", atDocStart: true, hasSelection: true })).toBeNull();
    expect(sectionArrowDecision({ ...base, key: "ArrowUp", onFirstLine: true, hasSelection: true })).toBeNull();
    expect(sectionArrowDecision({ ...base, key: "ArrowRight", atDocEnd: true, hasSelection: true })).toBeNull();
    expect(sectionArrowDecision({ ...base, key: "ArrowDown", onLastLine: true, hasSelection: true })).toBeNull();
  });
  it("an unrelated key declines", () => {
    expect(sectionArrowDecision({ ...base, key: "Backspace", atDocStart: true })).toBeNull();
  });
});

function fakeEvent(key: string, mods: Partial<Pick<KeyboardEvent, "shiftKey" | "ctrlKey" | "metaKey" | "altKey">> = {}) {
  return {
    key,
    shiftKey: false,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    ...mods,
    preventDefault: vi.fn(),
  } as unknown as KeyboardEvent;
}

function fakeView(opts: { pos: number; docSize: number; empty?: boolean }): EditorView {
  return {
    state: {
      // `parent.isTextblock: false` makes `inEdgeTextblock` decline without
      // walking a doc this fake doesn't have.
      selection: { $from: { pos: opts.pos, parent: { isTextblock: false } }, empty: opts.empty ?? true },
      doc: { content: { size: opts.docSize } },
    },
    // Headless (no layout) — first/last-line is never what's under test here.
    endOfTextblock: () => false,
  } as unknown as EditorView;
}

describe("handleSectionArrow — modifiers and missing neighbours (fake view)", () => {
  it("declines a Shift-held arrow even at a doc edge", () => {
    const next = vi.fn();
    const handled = handleSectionArrow(
      fakeView({ pos: 9, docSize: 10 }),
      fakeEvent("ArrowRight", { shiftKey: true }),
      { prev: null, next },
    );
    expect(handled).toBe(false);
    expect(next).not.toHaveBeenCalled();
  });
  it("declines a Ctrl/Cmd/Alt-held arrow even at a doc edge", () => {
    for (const mods of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }]) {
      const next = vi.fn();
      const handled = handleSectionArrow(fakeView({ pos: 9, docSize: 10 }), fakeEvent("ArrowRight", mods), {
        prev: null,
        next,
      });
      expect(handled).toBe(false);
      expect(next).not.toHaveBeenCalled();
    }
  });
  it("declines a non-arrow key", () => {
    const handled = handleSectionArrow(fakeView({ pos: 9, docSize: 10 }), fakeEvent("Backspace"), {
      prev: null,
      next: null,
    });
    expect(handled).toBe(false);
  });
  it("declines at a bridging edge with no wired neighbour", () => {
    const handled = handleSectionArrow(fakeView({ pos: 9, docSize: 10 }), fakeEvent("ArrowRight"), {
      prev: null,
      next: null,
    });
    expect(handled).toBe(false);
  });
});

// A REAL headless TipTap editor for the doc-edge cases (#1866 pattern). Both
// ArrowLeft-at-doc-start and ArrowRight-at-doc-end fire purely off
// `$from.pos`/`doc.content.size` — never `endOfTextblock` — so these two
// assertions hold even though happy-dom gives ProseMirror no real layout to
// measure a "first/last visual line" from (untested here for that reason).
describe("handleSectionArrow — real editor, doc-edge cases", () => {
  const editors: Editor[] = [];
  afterEach(() => {
    for (const editor of editors.splice(0)) editor.destroy();
  });

  function mount(): Editor {
    const editor = new Editor({
      element: document.createElement("div"),
      extensions: [proseStarterKit()],
      content: "<p>hello</p>",
    });
    editors.push(editor);
    return editor;
  }

  it("ArrowRight at doc end calls next and reports handled", () => {
    const editor = mount();
    editor.commands.setTextSelection(editor.state.doc.content.size - 1);
    const next = vi.fn();
    const handled = handleSectionArrow(editor.view, fakeEvent("ArrowRight"), { prev: null, next });
    expect(handled).toBe(true);
    expect(next).toHaveBeenCalledOnce();
  });

  it("ArrowLeft at doc start calls prev and reports handled", () => {
    const editor = mount();
    editor.commands.setTextSelection(1);
    const prev = vi.fn();
    const handled = handleSectionArrow(editor.view, fakeEvent("ArrowLeft"), { prev, next: null });
    expect(handled).toBe(true);
    expect(prev).toHaveBeenCalledOnce();
  });

  it("ArrowRight NOT at doc end does not call next", () => {
    const editor = mount();
    editor.commands.setTextSelection(2);
    const next = vi.fn();
    const handled = handleSectionArrow(editor.view, fakeEvent("ArrowRight"), { prev: null, next });
    expect(handled).toBe(false);
    expect(next).not.toHaveBeenCalled();
  });
});

describe("handleSectionArrow — multi-paragraph documents bridge only from the edge paragraph", () => {
  const editors: Editor[] = [];
  afterEach(() => {
    for (const editor of editors.splice(0)) editor.destroy();
  });

  function mountTwo(): Editor {
    const editor = new Editor({
      element: document.createElement("div"),
      extensions: [proseStarterKit()],
      content: "<p>one</p><p>two</p>",
    });
    editors.push(editor);
    // happy-dom has no layout, so `endOfTextblock` cannot answer "last visual
    // line"; simulate the layout saying yes so the doc-edge check alone decides.
    editor.view.endOfTextblock = () => true;
    return editor;
  }

  it("inEdgeTextblock: paragraph one is the start edge, paragraph two the end edge", () => {
    const editor = mountTwo();
    editor.commands.setTextSelection(2); // inside "one"
    expect(inEdgeTextblock(editor.state, "start")).toBe(true);
    expect(inEdgeTextblock(editor.state, "end")).toBe(false);
    editor.commands.setTextSelection(7); // inside "two"
    expect(inEdgeTextblock(editor.state, "start")).toBe(false);
    expect(inEdgeTextblock(editor.state, "end")).toBe(true);
  });

  it("ArrowDown on the last line of paragraph one does NOT bridge; on paragraph two it does", () => {
    const editor = mountTwo();
    const next = vi.fn();
    editor.commands.setTextSelection(2);
    expect(handleSectionArrow(editor.view, fakeEvent("ArrowDown"), { prev: null, next })).toBe(false);
    expect(next).not.toHaveBeenCalled();
    editor.commands.setTextSelection(7);
    expect(handleSectionArrow(editor.view, fakeEvent("ArrowDown"), { prev: null, next })).toBe(true);
    expect(next).toHaveBeenCalledOnce();
  });

  it("ArrowUp on the first line of paragraph two does NOT bridge; on paragraph one it does", () => {
    const editor = mountTwo();
    const prev = vi.fn();
    editor.commands.setTextSelection(7);
    expect(handleSectionArrow(editor.view, fakeEvent("ArrowUp"), { prev, next: null })).toBe(false);
    expect(prev).not.toHaveBeenCalled();
    editor.commands.setTextSelection(2);
    expect(handleSectionArrow(editor.view, fakeEvent("ArrowUp"), { prev, next: null })).toBe(true);
    expect(prev).toHaveBeenCalledOnce();
  });
});

describe("createSectionRegistry", () => {
  const editors: Editor[] = [];
  afterEach(() => {
    for (const editor of editors.splice(0)) editor.destroy();
  });
  function mount(): Editor {
    const editor = new Editor({ element: document.createElement("div"), extensions: [proseStarterKit()], content: "<p>a</p>" });
    editors.push(editor);
    return editor;
  }

  it("resolves prev/next by document order across the free body (0) and sections", () => {
    const registry = createSectionRegistry();
    const body = mount();
    const bio = mount();
    const goal = mount();
    registry.register(0, null, body);
    registry.register(1, "bio", bio);
    registry.register(2, "goal", goal);

    const bodyNeighbours: SectionNeighbours = registry.neighboursFor(0);
    expect(bodyNeighbours.prev).toBeNull();
    expect(bodyNeighbours.next).not.toBeNull();

    const bioNeighbours = registry.neighboursFor(1);
    expect(bioNeighbours.prev).not.toBeNull();
    expect(bioNeighbours.next).not.toBeNull();

    const goalNeighbours = registry.neighboursFor(2);
    expect(goalNeighbours.prev).not.toBeNull();
    expect(goalNeighbours.next).toBeNull();
  });

  it("focus on a list id lands on the list's first item editor in document order (#2052)", () => {
    const registry = createSectionRegistry();
    const bio = mount();
    const beat0function = mount();
    const beat0guidance = mount();
    const beat1function = mount();
    registry.register(1, "bio", bio);
    // Registered out of document order on purpose: the pick is by index, not insertion.
    registry.register(4, "beats[1].function", beat1function);
    registry.register(3, "beats[0].guidance", beat0guidance);
    registry.register(2, "beats[0].function", beat0function);
    // Park the caret at the END of the target so a focus at its start is observable.
    beat0function.commands.setTextSelection(beat0function.state.doc.content.size - 1);
    beat1function.commands.setTextSelection(beat1function.state.doc.content.size - 1);
    registry.focus("beats");
    expect(beat0function.state.selection.from).toBe(1);
    expect(beat1function.state.selection.from).not.toBe(1);
    // A direct id still wins over the prefix walk; an unknown id is a no-op.
    registry.focus("beats[1].function");
    expect(beat1function.state.selection.from).toBe(1);
    registry.focus("nothing");
  });

  it("unregister removes the named editor, by identity, from both maps", () => {
    const registry = createSectionRegistry();
    const body = mount();
    const bio = mount();
    registry.register(0, null, body);
    registry.register(1, "bio", bio);
    registry.unregister(bio);
    expect(registry.neighboursFor(0).next).toBeNull();
    registry.focus("bio");
    // no throw: "bio" is no longer in byField either.
  });

  it("registering a second editor at an index then unregistering the FIRST leaves the second registered", () => {
    const registry = createSectionRegistry();
    const first = mount();
    const second = mount();
    const goal = mount();
    registry.register(1, "bio", first);
    registry.register(2, "goal", goal);
    // A fast remount: the new instance registers at the same slot BEFORE the
    // old one's teardown runs (#2009 follow-up — the ordering hazard this
    // identity-based unregister exists to close).
    registry.register(1, "bio", second);
    registry.unregister(first);

    // byIndex: index 1 still resolves to `second` — `goal`'s "prev" bridges
    // into it (an index-keyed delete of `first`'s old slot would have wiped
    // this out from under `second`). `prev` is `focusEnd`, so the caret lands
    // at `second`'s doc end, not wherever it started.
    second.commands.setTextSelection(1);
    registry.neighboursFor(2).prev?.();
    expect(second.state.selection.from).toBe(second.state.doc.content.size - 1);

    // byField: "bio" still resolves to `second`, not evicted.
    registry.focus("bio");
    expect(second.state.selection.from).toBe(1);
  });

  it("unregistering an editor that was never registered is a no-op", () => {
    const registry = createSectionRegistry();
    const bio = mount();
    const stray = mount();
    registry.register(1, "bio", bio);
    registry.unregister(stray);
    expect(registry.neighboursFor(0).next).not.toBeNull(); // bio is still registered at 1
  });

  it("focuses the section registered for a field id", () => {
    const registry = createSectionRegistry();
    const bio = mount();
    registry.register(1, "bio", bio);
    bio.commands.setTextSelection(3);
    registry.focus("bio");
    expect(bio.state.selection.from).toBe(1);
  });
});
