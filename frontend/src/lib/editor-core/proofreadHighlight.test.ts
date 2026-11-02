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
import { MARK_CLASS, ProofreadHighlight, applyFix, dictionaryWord, findingAt, proofreadFindings } from "./proofreadHighlight";
import { ruleLabel } from "@/lib/proofread/ruleLabel";
import type { Finding } from "@/lib/proofread/findings";
import type { ProofreadLens } from "@/lib/stores/proofreading.svelte";
import type { ProofreadingSetup } from "@/lib/types";

/** What a layer's own file says: nothing. */
const own = { words: [] as string[], rules: {} as Record<string, boolean>, dialect: null };

/** A lens whose engine flags "teh" (fix: "the") and "recieve" (no fix),
 *  both under rule `ruleId`. */
function fakeLens(ruleId = "Fake") {
  const listeners = new Set<() => void>();
  const cache = new Map<string, Finding[]>();
  let accepted = new Set<string>();
  const lint = vi.fn(async (text: string) => {
    const findings: Finding[] = [];
    for (const m of text.matchAll(/\bteh\b|\brecieve\b/g)) {
      if (accepted.has(m[0])) continue;
      const from = m.index;
      const to = from + m[0].length;
      findings.push({
        engine: "fake",
        from,
        to,
        kind: m[0] === "teh" ? "Spelling" : "Grammar",
        ruleId,
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
    /** What a word change does: take the words, forget every result, say so. */
    acceptWords(words: string[]) {
      accepted = new Set(words);
      cache.clear();
      this.notify();
    },
    setup: {
      words: [],
      word_layers: {},
      rules: {},
      rule_layers: {},
      dialect: "american",
      layers: [
        { id: "lib", label: "Library", is_machine: false, is_library: true, is_root: false, ...own },
        { id: "machine", label: "Machine", is_machine: true, is_library: false, is_root: false, ...own },
        { id: "world", label: "Honorverse", is_machine: false, is_library: false, is_root: false, ...own },
        { id: "book", label: "Book 1", is_machine: false, is_library: false, is_root: true, ...own },
      ],
      ignored: {},
    } as ProofreadingSetup | null,
    addWord: vi.fn(async (_word: string, _layerId: string) => undefined),
    disableRule: vi.fn(async (_rule: string, _layerId: string) => undefined),
    ignoreHere: vi.fn(async (_nodeId: string, _text: string, _finding: Finding) => undefined),
  };
  return lens satisfies ProofreadLens & { notify(): void };
}

const editors: Editor[] = [];
afterEach(() => {
  for (const editor of editors.splice(0)) editor.destroy();
  document.querySelectorAll(".proofread-popover").forEach((el) => el.remove());
});

function setup(content: JSONContent[], lens = fakeLens(), enabled = () => true, nodeId: string | null = "manuscript_1") {
  const element = document.createElement("div");
  document.body.appendChild(element);
  const editor = new Editor({
    element,
    extensions: [proseStarterKit(), TodoAnchor, ProofreadHighlight.configure({ lens, enabled, nodeId: () => nodeId })],
    content: { type: "doc", content: content.map((c) => ({ type: "paragraph", content: [c] })) },
  });
  editors.push(editor);
  return { editor, lens };
}

const text = (t: string, marks?: JSONContent["marks"]): JSONContent => ({ type: "text", text: t, ...(marks ? { marks } : {}) });
/** Click the first underline reading `word`; the popover it opens. */
function openPopover(editor: Editor, word: string): HTMLElement {
  const mark = Array.from(editor.view.dom.querySelectorAll<HTMLElement>(`.${MARK_CLASS}`)).find((el) => el.textContent === word)!;
  mark.dispatchEvent(new MouseEvent("click", { bubbles: true, button: 0 }));
  return document.querySelector<HTMLElement>(".proofread-popover")!;
}
/** The popover's choice buttons by section heading ("" for the unheaded ones). */
function sections(popover: HTMLElement): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const box of popover.querySelectorAll(".proofread-popover-section")) {
    const heading = box.querySelector(".proofread-popover-heading")?.textContent ?? "";
    out[heading] = [...(out[heading] ?? []), ...Array.from(box.querySelectorAll("button"), (b) => b.textContent ?? "")];
  }
  return out;
}
const choose = (popover: HTMLElement, label: string) =>
  Array.from(popover.querySelectorAll<HTMLButtonElement>("button")).find((b) => b.textContent === label)!.click();

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
    popover.querySelector<HTMLButtonElement>(".proofread-popover-choice")!.click();

    expect(editor.state.doc.textContent).toBe("I saw the cat.");
    await vi.waitFor(() => expect(document.querySelector(".proofread-popover")).toBeNull());
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
    expect(proofreadFindings(editor.state).map((f) => f.text)).toEqual(["teh"]);
  });

  it("keeps the underline and an open popover through a redraw that changes nothing", async () => {
    const { editor, lens } = setup([text("I saw teh cat.")]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh"]));
    const mark = editor.view.dom.querySelector<HTMLElement>(`.${MARK_CLASS}`)!;
    mark.dispatchEvent(new MouseEvent("click", { bubbles: true, button: 0 }));
    let transactions = 0;
    editor.on("transaction", () => transactions++);
    lens.notify();
    await new Promise((r) => setTimeout(r, 80));
    expect(transactions).toBe(0);
    expect(mark.isConnected).toBe(true);
    expect(document.querySelector(".proofread-popover")).not.toBeNull();
  });

  it("never applies a fix to text that moved under an open popover", async () => {
    const { editor } = setup([text("I saw teh cat.")]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh"]));
    editor.view.dom.querySelector<HTMLElement>(`.${MARK_CLASS}`)!.dispatchEvent(new MouseEvent("click", { bubbles: true, button: 0 }));
    const button = document.querySelector<HTMLButtonElement>(".proofread-popover-choice")!;
    // Shift the flagged word right by five characters, before any relint.
    editor.view.dispatch(editor.state.tr.insertText("Yes, ", 1));
    button.click();
    expect(editor.state.doc.textContent).toBe("Yes, I saw teh cat.");
  });

  it("never applies a fix to another occurrence of the same word", async () => {
    const { editor } = setup([text("x teh y teh z")]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh", "teh"]));
    const second = editor.state.doc.textContent.lastIndexOf("teh") + 1;
    // Six characters in front: the text at the second finding's old offsets
    // (8–11) is now the FIRST "teh", shifted there.
    editor.view.dispatch(editor.state.tr.insertText("teh y ", 1));
    expect(editor.state.doc.textContent.slice(8, 11)).toBe("teh");
    const mapped = findingAt(editor.state, second + 6)!;
    expect(editor.state.doc.textBetween(mapped.from, mapped.to)).toBe("teh");
    expect(applyFix(editor.view, mapped, proofreadFindings(editor.state)[1].fixes[0])).toBe(false);
    expect(editor.state.doc.textContent).toBe("teh y x teh y teh z");
  });

  it("closes the popover when its finding goes away without an edit", async () => {
    const { editor, lens } = setup([text("I saw teh cat.")]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh"]));
    editor.view.dom.querySelector<HTMLElement>(`.${MARK_CLASS}`)!.dispatchEvent(new MouseEvent("click", { bubbles: true, button: 0 }));
    expect(document.querySelector(".proofread-popover")).not.toBeNull();
    lens.acceptWords(["teh"]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual([]));
    expect(document.querySelector(".proofread-popover")).toBeNull();
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

  it("offers the three permanent ignores, the dictionary for a spelling finding only", async () => {
    const { editor } = setup([text("I saw teh cat."), text("You recieve it.")]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh", "recieve"]));
    expect(sections(openPopover(editor, "teh"))).toEqual({
      "": ["the", "Ignore here"],
      "Add “teh” to the dictionary of": ["This machine", "Honorverse", "Book 1"],
      "Stop checking “Fake”": ["On this machine", "In this project"],
    });
    const grammar = sections(openPopover(editor, "recieve"));
    expect(Object.keys(grammar).some((h) => h.startsWith("Add"))).toBe(false);
  });

  it("routes each ignore to the lens with the right layer, rule and block text", async () => {
    const { editor, lens } = setup([text("I saw teh cat.")]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh"]));
    choose(openPopover(editor, "teh"), "Honorverse");
    await vi.waitFor(() => expect(lens.addWord).toHaveBeenCalledWith("teh", "world"));
    choose(openPopover(editor, "teh"), "In this project");
    await vi.waitFor(() => expect(lens.disableRule).toHaveBeenCalledWith("Fake", "book"));
    choose(openPopover(editor, "teh"), "Ignore here");
    await vi.waitFor(() => expect(lens.ignoreHere).toHaveBeenCalled());
    const [nodeId, blockTextArg, finding] = lens.ignoreHere.mock.calls[0];
    expect(nodeId).toBe("manuscript_1");
    expect(blockTextArg).toBe("I saw teh cat.");
    expect(finding.message).toBe("Check “teh”.");
    await vi.waitFor(() => expect(document.querySelector(".proofread-popover")).toBeNull());
  });

  it("keeps the popover open and says so when an ignore fails", async () => {
    const { editor, lens } = setup([text("I saw teh cat.")]);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh"]));
    lens.addWord.mockRejectedValueOnce(new Error("disk full"));
    const popover = openPopover(editor, "teh");
    choose(popover, "Book 1");
    await vi.waitFor(() => expect(popover.querySelector(".proofread-popover-error")?.textContent).toContain("disk full"));
    expect(popover.isConnected).toBe(true);
    expect(Array.from(popover.querySelectorAll("button")).every((b) => !b.disabled)).toBe(true);
  });

  it("never offers to switch spell checking itself off from one finding", async () => {
    const { editor } = setup([text("I saw teh cat.")], fakeLens("SpellCheck"));
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh"]));
    const offered = sections(openPopover(editor, "teh"));
    expect(Object.keys(offered).some((h) => h.startsWith("Stop checking"))).toBe(false);
    expect(Object.keys(offered).some((h) => h.startsWith("Add"))).toBe(true);
  });

  it("offers no ignore-here without an open node, and no ignores without a setup", async () => {
    const lens = fakeLens();
    const { editor } = setup([text("teh")], lens, () => true, null);
    await vi.waitFor(() => expect(underlined(editor)).toEqual(["teh"]));
    expect(sections(openPopover(editor, "teh"))[""]).toEqual(["the"]);
    lens.setup = null;
    expect(Object.keys(sections(openPopover(editor, "teh")))).toEqual([""]);
  });
});

describe("ruleLabel and dictionaryWord", () => {
  it("reads a rule name as words", () => {
    expect(ruleLabel("OxfordComma")).toBe("Oxford comma");
    expect(ruleLabel("SpellCheck")).toBe("Spell check");
    expect(ruleLabel("Catch22")).toBe("Catch22");
  });

  it("drops a possessive from a flagged word", () => {
    expect(dictionaryWord("Vashti's")).toBe("Vashti");
    expect(dictionaryWord("Ares’")).toBe("Ares");
    expect(dictionaryWord("Zorn")).toBe("Zorn");
  });
});
