// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor, type JSONContent } from "@tiptap/core";
import { TodoAnchor } from "./proseMarks";
import { proseStarterKit } from "./proseStarterKit";
import { TodoAnchors, createTodoId } from "./todoAnchors";

describe("createTodoId", () => {
  it("is `todo_` + 12 hex-ish characters", () => {
    expect(createTodoId()).toMatch(/^todo_[0-9a-f]{12}$/);
  });

  it("is different on every call", () => {
    expect(createTodoId()).not.toBe(createTodoId());
  });
});

describe("TodoAnchors.enforceUnique", () => {
  const editors: Editor[] = [];
  afterEach(() => {
    for (const editor of editors.splice(0)) editor.destroy();
  });
  const anchor = (anchorId: string): JSONContent["marks"] => [{ type: "todoAnchor", attrs: { anchorId, status: "open", note: "" } }];
  const text = (t: string, marks?: JSONContent["marks"]): JSONContent => ({ type: "text", text: t, ...(marks ? { marks } : {}) });
  function setup(...paragraphs: JSONContent[][]) {
    const editor = new Editor({
      element: document.createElement("div"),
      extensions: [proseStarterKit(), TodoAnchor],
      content: { type: "doc", content: paragraphs.map((content) => ({ type: "paragraph", content })) },
    });
    editors.push(editor);
    return { editor, anchors: new TodoAnchors({ getEditor: () => editor, getElement: () => null }) };
  }
  const marked = (editor: Editor) => {
    const out: string[] = [];
    editor.state.doc.descendants((node) => {
      if (node.marks.some((m) => m.type.name === "todoAnchor")) out.push(node.text ?? "");
    });
    return out;
  };

  it("keeps a contiguous run of one id across a mark boundary: it is one TODO", () => {
    const { editor, anchors } = setup([
      text("the ", anchor("todo_a")),
      text("old", [...(anchor("todo_a") ?? []), { type: "italic" }]),
      text(" docks", anchor("todo_a")),
    ]);
    expect(anchors.enforceUnique()).toBe(false);
    expect(marked(editor)).toEqual(["the ", "old", " docks"]);
  });

  it("strips a second, non-contiguous occurrence: another block, or after unmarked text", () => {
    const { editor, anchors } = setup(
      [text("one", anchor("todo_a")), text(" gap "), text("two", anchor("todo_a"))],
      [text("three", anchor("todo_a")), text(" and "), text("four", anchor("todo_b"))],
    );
    expect(anchors.enforceUnique()).toBe(true);
    expect(marked(editor)).toEqual(["one", "four"]);
  });

  it("strips a whole duplicate run, not just its first node", () => {
    const { editor, anchors } = setup(
      [text("first", anchor("todo_a"))],
      [text("x ", anchor("todo_a")), text("y", [...(anchor("todo_a") ?? []), { type: "italic" }])],
    );
    expect(anchors.enforceUnique()).toBe(true);
    expect(marked(editor)).toEqual(["first"]);
  });
});

describe("TodoAnchors.markRange", () => {
  it("marks the range without moving the selection, with a fresh id and the note", () => {
    const editor = new Editor({
      element: document.createElement("div"),
      extensions: [proseStarterKit(), TodoAnchor],
      content: "<p>The cat sat.</p>",
    });
    try {
      editor.commands.setTextSelection({ from: 2, to: 4 });
      const anchors = new TodoAnchors({ getEditor: () => editor, getElement: () => null });
      const id = anchors.markRange(5, 8, "why");
      expect(id).toMatch(/^todo_/);
      expect(editor.state.doc.nodeAt(5)?.marks[0].attrs).toMatchObject({ anchorId: id, status: "open", note: "why" });
      expect(editor.state.doc.textBetween(5, 8)).toBe("cat");
      expect(editor.state.selection).toMatchObject({ from: 2, to: 4 });
      expect(anchors.markRange(8, 8, "x")).toBeNull();
    } finally {
      editor.destroy();
    }
  });
});

describe("TodoAnchors.syncDomState", () => {
  it("renames data-todo-anchor-id to data-todo-id", () => {
    const element = document.createElement("div");
    element.innerHTML = `<span data-todo-anchor-id="todo_a"></span>`;
    const anchors = new TodoAnchors({ getEditor: () => null, getElement: () => element });

    anchors.syncDomState();

    const span = element.querySelector<HTMLElement>("span")!;
    expect(span.dataset.todoAnchorId).toBeUndefined();
    expect(span.dataset.todoId).toBe("todo_a");
  });

  it("sets the title from status for an anchor with no highlight in play", () => {
    const element = document.createElement("div");
    element.innerHTML = `
      <span data-todo-id="todo_a" data-todo-status="open"></span>
      <span data-todo-id="todo_b" data-todo-status="done"></span>
    `;
    const anchors = new TodoAnchors({ getEditor: () => null, getElement: () => element });

    anchors.syncDomState();

    const [open, done] = Array.from(element.querySelectorAll<HTMLElement>("span"));
    expect(open.title).toBe("Open TODO");
    expect(done.title).toBe("Completed TODO");
    expect(open.classList.contains("todo-anchor-highlight")).toBe(false);
    expect(done.classList.contains("todo-anchor-highlight")).toBe(false);
  });
});

describe("TodoAnchors.highlight", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("toggles todo-anchor-highlight on the highlighted id only, scrolls it into view, and clears after 2400ms", () => {
    const element = document.createElement("div");
    element.innerHTML = `
      <span data-todo-id="todo_a" data-todo-status="open"></span>
      <span data-todo-id="todo_b" data-todo-status="open"></span>
    `;
    const [a, b] = Array.from(element.querySelectorAll<HTMLElement>("span"));
    a.scrollIntoView = vi.fn();
    b.scrollIntoView = vi.fn();
    const anchors = new TodoAnchors({ getEditor: () => null, getElement: () => element });

    anchors.highlight("todo_a");

    expect(a.scrollIntoView).toHaveBeenCalledWith({ block: "center", behavior: "smooth" });
    expect(a.classList.contains("todo-anchor-highlight")).toBe(true);
    expect(b.classList.contains("todo-anchor-highlight")).toBe(false);

    vi.advanceTimersByTime(2400);

    expect(a.classList.contains("todo-anchor-highlight")).toBe(false);
  });

  it("is a no-op when the target isn't in the DOM", () => {
    const element = document.createElement("div");
    const anchors = new TodoAnchors({ getEditor: () => null, getElement: () => element });
    expect(() => anchors.highlight("todo_missing")).not.toThrow();
  });
});
