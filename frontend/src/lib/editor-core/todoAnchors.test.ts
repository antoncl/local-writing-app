// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TodoAnchors, createTodoId } from "./todoAnchors";

describe("createTodoId", () => {
  it("is `todo_` + 12 hex-ish characters", () => {
    expect(createTodoId()).toMatch(/^todo_[0-9a-f]{12}$/);
  });

  it("is different on every call", () => {
    expect(createTodoId()).not.toBe(createTodoId());
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
