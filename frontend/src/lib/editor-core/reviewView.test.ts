// @vitest-environment happy-dom
// #2561: Alt+A / Alt+S / Alt+B read an edit review as the page's words, the
// proposed ones, or both - a presentation state in the review plugin that never
// touches the document or resolves an item.
import { afterEach, describe, expect, it } from "vitest";
import { Editor } from "@tiptap/core";
import { proseStarterKit } from "./proseStarterKit";
import {
  LineEditSuggestions,
  acceptCurrentLineEdit,
  installLineEdits,
  lineEditState,
  setReviewView,
  toggleReviewView,
} from "./lineEditSuggestions";
import { reviewState } from "./reviewKinds/core";
import { placeLineEdits } from "./lineEdits";

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
});

const TEXT = "The cat sat on the mat.";

function setup(install = true) {
  const host = document.createElement("div");
  document.body.append(host);
  const editor = new Editor({
    element: host,
    extensions: [proseStarterKit(), LineEditSuggestions],
    content: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: TEXT }] }] },
  });
  editors.push(editor);
  if (install) {
    const { placed } = placeLineEdits(editor.state.doc, 0, editor.state.doc.content.size, [
      { find: "cat", replace: "dog", reason: "livelier" },
      { find: " on the mat", replace: " by the door", reason: "place" },
    ]);
    installLineEdits(editor.view, placed);
  }
  return editor;
}

const view = (editor: Editor) => reviewState(editor.state).view;

function key(editor: Editor, init: KeyboardEventInit): boolean {
  const event = new KeyboardEvent("keydown", { cancelable: true, ...init });
  return !!editor.view.someProp("handleKeyDown", (f) => f(editor.view, event));
}

describe("review view (#2561)", () => {
  it("starts as both, and toggling follows the snapshot strip's rule", () => {
    const editor = setup();
    expect(view(editor)).toBe("both");
    toggleReviewView("now", editor.view);
    expect(view(editor)).toBe("now");
    toggleReviewView("now", editor.view);
    expect(view(editor)).toBe("both");
    toggleReviewView("proposed", editor.view);
    expect(view(editor)).toBe("proposed");
    toggleReviewView("now", editor.view);
    expect(view(editor)).toBe("now");
    setReviewView("both", editor.view);
    expect(view(editor)).toBe("both");
  });

  it("a fresh install resets the view to both", () => {
    const editor = setup();
    setReviewView("proposed", editor.view);
    const { placed } = placeLineEdits(editor.state.doc, 0, editor.state.doc.content.size, [
      { find: "cat", replace: "dog", reason: "livelier" },
    ]);
    installLineEdits(editor.view, placed);
    expect(view(editor)).toBe("both");
  });

  it("never changes the document or the item list", () => {
    const editor = setup();
    const before = lineEditState(editor.state).edits.map((e) => ({ id: e.id, from: e.from, to: e.to }));
    setReviewView("proposed", editor.view);
    setReviewView("now", editor.view);
    expect(editor.state.doc.textContent).toBe(TEXT);
    expect(lineEditState(editor.state).edits.map((e) => ({ id: e.id, from: e.from, to: e.to }))).toEqual(before);
  });

  it("accept still writes the replacement while reading the proposed version", () => {
    const editor = setup();
    setReviewView("proposed", editor.view);
    acceptCurrentLineEdit(editor.view);
    expect(editor.state.doc.textContent).toBe("The dog sat on the mat.");
    expect(lineEditState(editor.state).edits).toHaveLength(1);
    expect(view(editor)).toBe("proposed");
  });

  it("Alt+A / Alt+S / Alt+B (by code) set the view and are handled", () => {
    const editor = setup();
    expect(key(editor, { altKey: true, code: "KeyA", key: "å" })).toBe(true);
    expect(view(editor)).toBe("now");
    expect(key(editor, { altKey: true, code: "KeyS", key: "ß" })).toBe(true);
    expect(view(editor)).toBe("proposed");
    expect(key(editor, { altKey: true, code: "KeyS", key: "s" })).toBe(true);
    expect(view(editor)).toBe("both");
    key(editor, { altKey: true, code: "KeyA", key: "a" });
    expect(key(editor, { altKey: true, code: "KeyB", key: "∫" })).toBe(true);
    expect(view(editor)).toBe("both");
    // By key alone too.
    expect(key(editor, { altKey: true, key: "A" })).toBe(true);
    expect(view(editor)).toBe("now");
  });

  it("a plain letter, or a chorded one, is left to type", () => {
    const editor = setup();
    expect(key(editor, { code: "KeyA", key: "a" })).toBe(false);
    expect(key(editor, { altKey: true, ctrlKey: true, code: "KeyA", key: "a" })).toBe(false);
    expect(key(editor, { altKey: true, shiftKey: true, code: "KeyA", key: "A" })).toBe(false);
    expect(view(editor)).toBe("both");
  });

  it("does nothing without a review", () => {
    const editor = setup(false);
    expect(key(editor, { altKey: true, code: "KeyA", key: "a" })).toBe(false);
    expect(view(editor)).toBe("both");
  });

  it("the root carries a class per view, and none for both", () => {
    const editor = setup();
    const dom = editor.view.dom;
    expect(dom.className).not.toMatch(/review-view/);
    setReviewView("now", editor.view);
    expect(dom.classList.contains("review-view-now")).toBe(true);
    setReviewView("proposed", editor.view);
    expect(dom.classList.contains("review-view-proposed")).toBe(true);
    expect(dom.classList.contains("review-view-now")).toBe(false);
    setReviewView("both", editor.view);
    expect(dom.className).not.toMatch(/review-view/);
  });

  it("marks the new-words widget so the CSS can reach it, and the going words as r-now", () => {
    const editor = setup();
    const dom = editor.view.dom;
    const added = dom.querySelector(".r-was");
    expect(added?.classList.contains("line-edit-added")).toBe(true);
    // The widget is a sibling of the passage's spans, not inside `.line-edit`;
    // the going words are the same span as `.line-edit` (ProseMirror merges them).
    expect(added?.closest(".line-edit")).toBeNull();
    expect(dom.querySelector(".line-edit.r-now")).not.toBeNull();
  });
});
