// @vitest-environment happy-dom
// The implicit-context hover card (#1923) against a real TipTap editor: it is
// shown for exactly one attached match under the pointer and hides the moment
// that stops being true, and it follows the match to its entry.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import { HIDE_DELAY_MS, ImplicitContextHighlight } from "./implicitContextHighlight";
import { compileMatcher } from "./implicitContextMatcher";
import { implicitContextOpener } from "./implicitContextOpen";
import type { LoreEntrySummary } from "@/lib/types";

const matcher = compileMatcher([
  { id: "lore_alice", title: "Alice", entry_type: "character", metadata: { aliases: [] }, body: "A courier." } as LoreEntrySummary,
]);

// Every editor is destroyed after its test — a live view schedules a DOM
// observer flush that would fire after the environment is torn down. Its
// destroy is also the only thing that removes a card: a stray one is a bug.
const editors: Editor[] = [];

function editorWith(html: string): Editor {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [StarterKit, ImplicitContextHighlight.configure({ matcher })],
    content: html,
  });
  editors.push(editor);
  return editor;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
  implicitContextOpener.open = null;
  vi.useRealTimers();
});

const match = (editor: Editor): HTMLElement => {
  const span = editor.view.dom.querySelector<HTMLElement>(".implicit-context-match");
  if (!span) throw new Error("no match decorated");
  return span;
};
/** The card is on the page exactly while it is shown. */
const card = (): HTMLElement | null => document.body.querySelector<HTMLElement>(".implicit-context-popup");
const mouse = (el: Element, type: string, init: MouseEventInit = {}) =>
  el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, ...init }));
/** Both modifiers, so the gesture follows the name on every platform. */
const modified: MouseEventInit = { ctrlKey: true, metaKey: true };
/** Past the bridge delay the card waits before hiding. */
const settle = () => vi.advanceTimersByTime(HIDE_DELAY_MS + 1);

describe("implicit-context hover card", () => {
  it("shows for a hovered match and hides once the pointer is over text that is not a match", () => {
    const editor = editorWith("<p>Alice walked.</p>");
    mouse(match(editor), "mouseover");
    expect(card()?.textContent).toContain("Alice");
    expect(card()?.getAttribute("aria-label")).toBe("Alice");

    mouse(editor.view.dom, "mouseover");
    settle();
    expect(card()).toBeNull();
  });

  it("does not keep postponing the hide while the pointer sweeps across text that is not a match", () => {
    const editor = editorWith("<p>Alice walked.</p>");
    mouse(match(editor), "mouseover");
    mouse(editor.view.dom, "mouseover");
    vi.advanceTimersByTime(HIDE_DELAY_MS / 2);
    mouse(editor.view.dom, "mouseover");
    vi.advanceTimersByTime(HIDE_DELAY_MS / 2 + 1);
    expect(card()).toBeNull();
  });

  it("hides when the span it was shown for leaves the view — a rescan re-renders it, and no mouseout ever comes", () => {
    const editor = editorWith("<p>Alice walked.</p>");
    mouse(match(editor), "mouseover");
    expect(card()).not.toBeNull();

    // Editing inside the name changes the match, so the rescan re-renders it.
    editor.commands.insertContentAt(3, "x");
    expect(editor.view.dom.contains(card()?.parentElement ?? null)).toBe(false);
    expect(card()).toBeNull();
  });

  it("stays through an edit elsewhere that leaves the name attached", () => {
    const editor = editorWith("<p>Alice walked.</p>");
    const span = match(editor);
    mouse(span, "mouseover");

    editor.commands.insertContentAt(editor.state.doc.content.size - 1, " on");
    expect(editor.view.dom.contains(span)).toBe(true);
    expect(card()).not.toBeNull();
  });

  it("hides on Escape — consumed, so the dialog around the editor stays — and on a pointer-down anywhere else", () => {
    const editor = editorWith("<p>Alice walked.</p>");
    mouse(match(editor), "mouseover");
    const escape = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    document.body.dispatchEvent(escape);
    expect(card()).toBeNull();
    expect(escape.defaultPrevented).toBe(true);

    mouse(match(editor), "mouseover");
    expect(card()).not.toBeNull();
    document.body.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    expect(card()).toBeNull();
  });

  it("hides when the pointer leaves the name for outside the editor", () => {
    const editor = editorWith("<p>Alice walked.</p>");
    mouse(match(editor), "mouseover");
    mouse(match(editor), "mouseout", { relatedTarget: document.body });
    settle();
    expect(card()).toBeNull();
  });

  it("stays while the pointer crosses from the name onto the card, and hides when it leaves the card", () => {
    const editor = editorWith("<p>Alice walked.</p>");
    const span = match(editor);
    mouse(span, "mouseover");
    const el = card();
    if (!el) throw new Error("no card");

    mouse(span, "mouseout", { relatedTarget: el });
    mouse(el, "mouseenter");
    settle();
    expect(card()).toBe(el);

    mouse(el, "mouseleave");
    settle();
    expect(card()).toBeNull();
  });

  it("follows the match to its entry from the card's title and from a modifier-click on the name", () => {
    const open = vi.fn();
    implicitContextOpener.open = open;
    const editor = editorWith("<p>Alice walked.</p>");
    mouse(match(editor), "mouseover");
    const title = card()?.querySelector<HTMLButtonElement>("button.implicit-context-popup-open");
    expect(title?.textContent).toBe("Alice");
    title?.click();
    expect(open).toHaveBeenCalledWith("lore_alice");
    expect(card()).toBeNull();

    mouse(match(editor), "click", modified);
    expect(open).toHaveBeenCalledTimes(2);
  });

  it("claims the modifier mousedown so the caret does not move, and leaves a plain click alone", () => {
    implicitContextOpener.open = vi.fn();
    const editor = editorWith("<p>Alice walked.</p>");
    const down = new MouseEvent("mousedown", { bubbles: true, cancelable: true, ...modified });
    match(editor).dispatchEvent(down);
    expect(down.defaultPrevented).toBe(true);

    const plain = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    match(editor).dispatchEvent(plain);
    expect(plain.defaultPrevented).toBe(false);
    mouse(match(editor), "click");
    expect(implicitContextOpener.open).not.toHaveBeenCalled();
  });

  it("has no link while no opener is wired", () => {
    const editor = editorWith("<p>Alice walked.</p>");
    mouse(match(editor), "mouseover");
    expect(card()?.querySelector("button")).toBeNull();
    expect(card()?.querySelector(".implicit-context-popup-title")?.textContent).toBe("Alice");
    mouse(match(editor), "click", modified);
    expect(card()).not.toBeNull();
  });

  it("goes with the view", () => {
    const editor = editorWith("<p>Alice walked.</p>");
    mouse(match(editor), "mouseover");
    expect(card()).not.toBeNull();
    editor.destroy();
    expect(card()).toBeNull();
  });
});
