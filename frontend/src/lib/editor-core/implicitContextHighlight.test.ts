// @vitest-environment happy-dom
// The implicit-context hover card (#1923) against a real TipTap editor: it is
// shown for exactly one attached match under the pointer and hides the moment
// that stops being true, and it follows the match to its entry.
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import { ImplicitContextHighlight } from "./implicitContextHighlight";
import { compileMatcher } from "./implicitContextMatcher";
import type { LoreEntrySummary } from "@/lib/types";

const matcher = compileMatcher([
  { id: "lore_alice", title: "Alice", entry_type: "character", metadata: { aliases: [] }, body: "A courier." } as LoreEntrySummary,
]);

// Every editor is destroyed after its test — a live view schedules a DOM
// observer flush that would fire after the environment is torn down.
const editors: Editor[] = [];

function editorWith(html: string, openEntry: ((entryId: string) => void) | null = null): Editor {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [StarterKit, ImplicitContextHighlight.configure({ matcher, openEntry })],
    content: html,
  });
  editors.push(editor);
  return editor;
}

afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
  for (const stray of document.body.querySelectorAll(".implicit-context-popup")) stray.remove();
});

const match = (editor: Editor): HTMLElement => {
  const span = editor.view.dom.querySelector<HTMLElement>(".implicit-context-match");
  if (!span) throw new Error("no match decorated");
  return span;
};
const card = (): HTMLElement | null => document.body.querySelector<HTMLElement>(".implicit-context-popup");
const shown = (): boolean => card()?.style.display === "block";
const mouse = (el: Element, type: string, init: MouseEventInit = {}) =>
  el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, ...init }));
/** Past the bridge delay the card waits before hiding. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 120));

describe("implicit-context hover card", () => {
  it("shows for a hovered match and hides once the pointer is over text that is not a match", async () => {
    const editor = editorWith("<p>Alice walked.</p>");
    mouse(match(editor), "mouseover");
    expect(shown()).toBe(true);
    expect(card()?.textContent).toContain("Alice");

    mouse(editor.view.dom, "mouseover");
    await settle();
    expect(shown()).toBe(false);
  });

  it("hides when the document changes under the pointer — typing re-renders the span, so no mouseout ever comes", () => {
    const editor = editorWith("<p>Alice walked.</p>");
    const span = match(editor);
    mouse(span, "mouseover");
    expect(shown()).toBe(true);

    editor.commands.insertContentAt(editor.state.doc.content.size - 1, " on");
    expect(shown()).toBe(false);
  });

  it("hides on Escape and when the pointer leaves the editor", async () => {
    const editor = editorWith("<p>Alice walked.</p>");
    mouse(match(editor), "mouseover");
    editor.view.dom.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(shown()).toBe(false);

    mouse(match(editor), "mouseover");
    expect(shown()).toBe(true);
    mouse(editor.view.dom, "mouseleave");
    await settle();
    expect(shown()).toBe(false);
  });

  it("stays while the pointer crosses from the name onto the card, and hides when it leaves the card", async () => {
    const editor = editorWith("<p>Alice walked.</p>");
    const span = match(editor);
    mouse(span, "mouseover");
    const el = card();
    if (!el) throw new Error("no card");

    mouse(span, "mouseout", { relatedTarget: el });
    mouse(el, "mouseenter");
    await settle();
    expect(shown()).toBe(true);

    mouse(el, "mouseleave");
    await settle();
    expect(shown()).toBe(false);
  });

  it("follows the match to its entry from the card's title and from Ctrl+click on the name; a plain click places the caret", () => {
    const openEntry = vi.fn();
    const editor = editorWith("<p>Alice walked.</p>", openEntry);
    mouse(match(editor), "mouseover");
    const title = card()?.querySelector<HTMLButtonElement>("button.implicit-context-popup-open");
    expect(title?.textContent).toBe("Alice");
    title?.click();
    expect(openEntry).toHaveBeenCalledWith("lore_alice");
    expect(shown()).toBe(false);

    mouse(match(editor), "click");
    expect(openEntry).toHaveBeenCalledTimes(1);
    mouse(match(editor), "click", { ctrlKey: true });
    expect(openEntry).toHaveBeenCalledTimes(2);
  });

  it("has no link without an opener", () => {
    const editor = editorWith("<p>Alice walked.</p>");
    mouse(match(editor), "mouseover");
    expect(card()?.querySelector("button")).toBeNull();
    expect(card()?.querySelector(".implicit-context-popup-title")?.textContent).toBe("Alice");
  });

  it("goes with the view", () => {
    const editor = editorWith("<p>Alice walked.</p>");
    mouse(match(editor), "mouseover");
    expect(card()).not.toBeNull();
    editors.splice(editors.indexOf(editor), 1);
    editor.destroy();
    expect(card()).toBeNull();
  });
});
