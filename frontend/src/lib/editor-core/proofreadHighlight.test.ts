// @vitest-environment happy-dom
// Proofreading (ADR-0102 §3) against a real TipTap editor: findings draw only
// while the lens is active, a click opens the popover, a fix is one undoable
// edit that keeps a TODO anchor, an edited block keeps its underlines until its
// new result lands, and a fix whose text changed underneath does nothing.
import { afterEach, describe, expect, it, vi } from "vitest";
import { Editor, type JSONContent } from "@tiptap/core";
import { undo } from "@tiptap/pm/history";
import { proseStarterKit } from "./proseStarterKit";
import { TodoAnchor } from "./proseMarks";
import { MARK_CLASS, ProofreadHighlight, applyFix, findingAt, proofreadFindings } from "./proofreadHighlight";
import type { Finding } from "@/lib/proofread/findings";
import type { ProofreadLens } from "@/lib/stores/proofreading.svelte";

/** A lens whose engine flags "teh" (fix: "the") and "recieve" (no fix). */
function fakeLens() {
  const listeners = new Set<() => void>();
  const cache = new Map<string, Finding[]>();
  const lint = vi.fn(async (text: string) => {
    const findings: Finding[] = [];
    for (const m of text.matchAll(/\bteh\b|\brecieve\b/g)) {
      const from = m.index;
      const to = from + m[0].length;
      findings.push({
        engine: "fake",
        from,
        to,
        kind: m[0] === "teh" ? "Spelling" : "Grammar",
        ruleId: "Fake",
        message: `Check “${m[0]}”.`,
        fixes: m[0] === "teh" ? [{ label: "the", from, to, insert: "the" }] : [],
      });
    }
    cache.set(text, findings);
    return findings;
  });
  const lens = {
    active: true,
    cached: (text: string) => cache.get(text),
    lint,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    notify: () => listeners.forEach((l) => l()),
  };
  return lens satisfies ProofreadLens & { notify(): void };
}

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
  document.querySelectorAll(".proofread-popover").forEach((el) => el.remove());
});

function setup(content: JSONContent[], lens = fakeLens(), enabled = () => true) {
  const element = document.createElement("div");
  document.body.appendChild(element);
  const editor = new Editor({
    element,
    extensions: [proseStarterKit(), TodoAnchor, ProofreadHighlight.configure({ lens, enabled })],
    content: { type: "doc", content: content.map((c) => ({ type: "paragraph", content: [c] })) },
  });
  editors.push(editor);
  return { editor, lens };
}

const text = (t: string, marks?: JSONContent["marks"]): JSONContent => ({ type: "text", text: t, ...(marks ? { marks } : {}) });
const underlined = (editor: Editor) => Array.from(editor.view.dom.querySelectorAll(`.${MARK_CLASS}`), (el) => el.textContent);

describe("ProofreadHighlight", () => {
  it("underlines findings, spelling and other kinds apart", async () => {
    const { editor } = setup([text("I saw teh cat."), text("You recieve it.")]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh", "recieve"]));
    expect(editor.view.dom.querySelector(".proofread-spelling")?.textContent).toBe("teh");
    expect(editor.view.dom.querySelector(".proofread-issue")?.textContent).toBe("recieve");
  });

  it("draws nothing for an editor that doesn't proofread, or while the lens is off", async () => {
    const off = setup([text("teh")], fakeLens(), () => false);
    const lens = fakeLens();
    lens.active = false;
    const inactive = setup([text("teh")], lens);
    // Long enough for a lint to land and be drawn (the redraw waits 40ms).
    await new Promise((r) => setTimeout(r, 120));
    expect(underlined(off.editor)).toEqual([]);
    expect(off.lens.lint).not.toHaveBeenCalled();
    expect(underlined(inactive.editor)).toEqual([]);
    expect(lens.lint).not.toHaveBeenCalled();
  });

  it("clears every underline and restores spellcheck when the lens goes off", async () => {
    const { editor, lens } = setup([text("teh")]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh"]));
    expect(editor.view.dom.getAttribute("spellcheck")).toBe("false");
    lens.active = false;
    lens.notify();
    await vi.waitFor(() => expect(underlined(editor)).toEqual([]));
    expect(editor.view.dom.getAttribute("spellcheck")).not.toBe("false");
  });

  it("opens the popover on a click and applies a fix as one undoable edit that keeps a TODO anchor", async () => {
    const anchor = [{ type: "todoAnchor", attrs: { anchorId: "todo_1", status: "open", note: "" } }];
    const { editor } = setup([text("I saw teh cat.", anchor)]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh"]));
    const mark = editor.view.dom.querySelector<HTMLElement>(`.${MARK_CLASS}`)!;
    mark.dispatchEvent(new MouseEvent("click", { bubbles: true, button: 0 }));
    const popover = document.querySelector(".proofread-popover")!;
    expect(popover.textContent).toContain("Check “teh”.");
    popover.querySelector<HTMLButtonElement>(".proofread-popover-fix")!.click();

    expect(editor.state.doc.textContent).toBe("I saw the cat.");
    expect(document.querySelector(".proofread-popover")).toBeNull();
    const anchored: string[] = [];
    editor.state.doc.descendants((node) => {
      if (node.marks.some((m) => m.type.name === "todoAnchor")) anchored.push(node.text ?? "");
    });
    expect(anchored.join("")).toBe("I saw the cat.");
    undo(editor.state, editor.view.dispatch);
    expect(editor.state.doc.textContent).toBe("I saw teh cat.");
  });

  it("keeps a block's underlines through an edit elsewhere in it until its new result lands", async () => {
    const { editor, lens } = setup([text("I saw teh cat.")]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh"]));
    editor.commands.insertContentAt(1, "Yes, ");
    // Mapped, not dropped: still under the same word straight after the edit.
    expect(underlined(editor)).toEqual(["teh"]);
    await vi.waitFor(() => expect(lens.lint).toHaveBeenCalledWith("Yes, I saw teh cat."), { timeout: 2000 });
    expect(proofreadFindings(editor.state).map((f) => f.problem)).toEqual(["teh"]);
  });

  it("refuses a fix once the text under the finding has changed", async () => {
    const { editor } = setup([text("I saw teh cat.")]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh"]));
    const at = editor.state.doc.textContent.indexOf("teh") + 1;
    const deco = findingAt(editor.state, at)!;
    const fix = proofreadFindings(editor.state)[0].fixes[0];
    // Change the flagged word itself without remapping the decoration.
    editor.view.dispatch(editor.state.tr.insertText("x", at + 1, at + 2));
    expect(applyFix(editor.view, deco, fix)).toBe(false);
    expect(editor.state.doc.textContent).toBe("I saw txh cat.");
  });
});
