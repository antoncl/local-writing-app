// @vitest-environment happy-dom
// ADR-0100: flags placed from a conversation - placement over the whole scene,
// the unplaceable count, notes without an entry, and the controller's single
// mixed review (real TipTap editor + real AiSuggestionController + real plugin).
import { afterEach, describe, expect, it } from "vitest";
import { Editor, type JSONContent } from "@tiptap/core";
import { proseStarterKit } from "./proseStarterKit";
import { AiSuggestionController } from "./aiSuggestion.svelte";
import { LineEditSuggestions, lineEditState, lineNoteState } from "./lineEditSuggestions";
import { flagEntryNames, flagsNotice, placeSceneFlags, type SceneFlags } from "./conversationFlags";
import { buildLineNoteCard } from "./lineNoteCard";
import { noteKeepNote } from "./keepFlag";
import { reviewState } from "./reviewKinds/core";

const editors: Editor[] = [];
afterEach(() => {
  for (const e of editors.splice(0)) e.destroy();
});

const para = (t: string): JSONContent => ({ type: "paragraph", content: [{ type: "text", text: t }] });

function setup() {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit(), LineEditSuggestions],
    content: { type: "doc", content: [para("The cat sat on the mat."), para("Mira walked to the Keep.")] },
  });
  editors.push(editor);
  const notices: string[] = [];
  const ctrl = new AiSuggestionController({
    getEditor: () => editor,
    getEditorFrame: () => undefined,
    getScene: () => ({ id: "scene_1", entry_type: "manuscript:scene" }) as never,
    getDocumentKind: () => "manuscript",
    getPromptCtx: () => ({ metadataSchema: { entry_types: {}, fields: {} }, promptEntries: [] }) as never,
    onInvocationCost: () => {},
    addCharacterCost: () => {},
    onRequestInputsDialog: () => {},
    onNotice: (m) => notices.push(m),
    onOpenChat: () => {},
  });
  return { editor, ctrl, notices };
}

const FLAGS: SceneFlags = {
  edits: [{ find: "sat on the mat", replace: "slept", reason: "tighter" }],
  notes: [
    { quote: "Mira", problem: "Who is Mira here?", entry_id: "lore_1", entry_name: "Mira" },
    { quote: "walked", problem: "Too plain", entry_id: null, entry_name: null },
  ],
};

describe("placeSceneFlags", () => {
  it("places edits and notes across two paragraphs and counts what it cannot place", () => {
    const { editor } = setup();
    const flags: SceneFlags = {
      edits: [...FLAGS.edits, { find: "not in the scene", replace: "x", reason: "r" }],
      notes: [...FLAGS.notes, { quote: "the", problem: "ambiguous", entry_id: null, entry_name: null }],
    };
    const placed = placeSceneFlags(editor.state.doc, flags);
    expect(placed.edits.map((e) => e.find)).toEqual(["sat on the mat"]);
    expect(placed.notes.map((n) => n.quote)).toEqual(["Mira", "walked"]);
    expect(placed.notes.map((n) => n.entry)).toEqual(["lore_1", ""]);
    expect(placed.dropped).toBe(2);
    expect(placed.total).toBe(5);
  });

  it("words the notice for some and for none", () => {
    expect(flagsNotice(0, 3)).toBeNull();
    expect(flagsNotice(2, 9)).toBe("2 of 9 flags couldn't be found in the scene.");
    expect(flagsNotice(4, 4)).toBe("None of the 4 flags could be found in the scene.");
  });

  it("names entries from the response's notes", () => {
    expect([...flagEntryNames(FLAGS)]).toEqual([["lore_1", "Mira"]]);
  });
});

describe("a note without an entry (ADR-0100 §7)", () => {
  const actions = { prev: () => {}, next: () => {}, openEntry: () => {}, keep: () => {}, dismiss: () => {} };
  const testids = (card: HTMLElement) => [...card.querySelectorAll("[data-testid]")].map((e) => (e as HTMLElement).dataset.testid);

  it("renders no entry line and no Open entry button", () => {
    const card = buildLineNoteCard("Too plain", "", false, actions);
    expect(testids(card)).not.toContain("line-note-card-entry");
    expect(testids(card)).not.toContain("line-note-card-open");
    expect(card.querySelector("[data-testid=line-note-card-keep]")).not.toBeNull();
    const first = card.querySelector(".lec-actions")?.firstElementChild as HTMLElement;
    expect(first.dataset.testid).toBe("line-note-card-keep");
  });

  it("still renders the entry line and Open entry for a note with an entry", () => {
    const card = buildLineNoteCard("Who is Mira?", "Mira", false, actions);
    expect(card.querySelector("[data-testid=line-note-card-entry]")?.textContent).toBe("Mira");
    expect(card.querySelector("[data-testid=line-note-card-open]")).not.toBeNull();
  });

  it("keeps the problem alone as the TODO text", () => {
    expect(noteKeepNote("Too plain", "")).toBe("Too plain");
    expect(noteKeepNote("Who is Mira?", "Mira")).toBe("Who is Mira? (Mira)");
  });
});

describe("AiSuggestionController.installConversationFlags", () => {
  it("opens one review over both kinds and counts its items", () => {
    const { editor, ctrl, notices } = setup();
    ctrl.installConversationFlags({
      ...FLAGS,
      notes: [...FLAGS.notes, { quote: "missing", problem: "gone", entry_id: null, entry_name: null }],
    });
    expect(ctrl.flags).toEqual({ remaining: 3, index: 1, edits: 1 });
    expect(ctrl.lineEdits).toBeNull();
    expect(ctrl.lineNotes).toBeNull();
    expect(lineEditState(editor.state).edits).toHaveLength(1);
    expect(lineNoteState(editor.state).notes).toHaveLength(2);
    expect(notices).toEqual(["1 of 4 flags couldn't be found in the scene."]);
    ctrl.nextFlag();
    expect(ctrl.flags?.index).toBe(2);
    ctrl.prevFlag();
    expect(ctrl.flags?.index).toBe(1);
  });

  it("closes the run when every flag is resolved", () => {
    const { editor, ctrl } = setup();
    ctrl.installConversationFlags(FLAGS);
    ctrl.acceptAllFlagEdits();
    expect(editor.state.doc.textContent).toContain("The cat slept.");
    expect(ctrl.flags).toEqual({ remaining: 2, index: 1, edits: 0 });
    ctrl.rejectAllFlags();
    expect(reviewState(editor.state).items).toHaveLength(0);
    expect(ctrl.flags).toBeNull();
  });

  it("installing while a run is open replaces it", () => {
    const { editor, ctrl } = setup();
    ctrl.installConversationFlags(FLAGS);
    ctrl.installConversationFlags({ edits: [], notes: [FLAGS.notes[1]] });
    expect(ctrl.flags).toEqual({ remaining: 1, index: 1, edits: 0 });
    expect(lineEditState(editor.state).edits).toHaveLength(0);
    ctrl.rejectAllFlags();
    expect(ctrl.flags).toBeNull();
  });

  it("opens nothing, and says so, when none can be placed", () => {
    const { ctrl, notices } = setup();
    ctrl.installConversationFlags({ edits: [{ find: "nope", replace: "x", reason: "r" }], notes: [] });
    expect(ctrl.flags).toBeNull();
    expect(notices).toEqual(["None of the 1 flags could be found in the scene."]);
  });

  it("refuses to start a prompt run while a flags run is open", async () => {
    const { ctrl, notices } = setup();
    ctrl.installConversationFlags(FLAGS);
    await ctrl.runPromptEntry({ id: "p", title: "P", entry_type: "prompt:general", offer_on: ["manuscript:scene"] } as never);
    expect(notices.some((m) => m.includes("Finish reviewing the flags first"))).toBe(true);
  });
});
