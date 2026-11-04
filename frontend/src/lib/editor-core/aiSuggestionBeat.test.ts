// @vitest-environment happy-dom
// Accepting a roleplay turn brackets the reply as ONE beat, however many
// paragraphs it has, and a turn can't start inside a beat (ADR-0070
// Amendment 1, decisions 1 and 5). Drives the real controller with a faked
// stream, like aiSuggestionStream.test.ts.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { api } from "@/lib/api";
import { AISuggestion } from "./proseMarks";
import { proseStarterKit } from "./proseStarterKit";
import { BeatCloseMarker, BeatOpenMarker } from "./beatMarkers";
import { scanBeats } from "./beats";
import { AiSuggestionController } from "./aiSuggestion.svelte";
import { editorHtmlToSceneMarkdown, sceneMarkdownToHtml } from "../utils/markdown";

const editors: Editor[] = [];
beforeEach(() => {
  vi.spyOn(api, "aiAppendInvocation").mockResolvedValue(undefined as never);
});
afterEach(() => {
  vi.restoreAllMocks();
  for (const editor of editors.splice(0)) editor.destroy();
});

const ROLEPLAY = {
  id: "p_roleplay",
  title: "Roleplay",
  body: "x",
  entry_type: "prompt:general",
  context_strategy: { output: { handler: "inline", on_accept: { mark: "character", from_input: "character" } } },
} as never;
const ELIAS = JSON.stringify([{ id: "lore_elias", kind: "lore" }]);

async function setup(markdown = "") {
  const notices: string[] = [];
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit(), AISuggestion, BeatOpenMarker, BeatCloseMarker],
    content: await sceneMarkdownToHtml(markdown),
  });
  editors.push(editor);
  const ctrl = new AiSuggestionController({
    getEditor: () => editor,
    getEditorFrame: () => undefined,
    getScene: () => ({ id: "scene_1" }) as never,
    getDocumentKind: () => "manuscript",
    getPromptCtx: () => ({ promptEntries: [ROLEPLAY], loreEntries: [{ id: "lore_elias", title: "Elias" }] }) as never,
    onInvocationCost: () => {},
    addCharacterCost: () => {},
    onRequestInputsDialog: () => {},
    onOpenChat: () => {},
    onNotice: (message: string) => notices.push(message),
  });
  return { editor, ctrl, notices };
}

function fakeStream(text: string) {
  return vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
    yield { type: "delta", text } as never;
    yield { type: "done", provider: "p", model: "m", latency_ms: 1, truncated: false } as never;
  });
}

describe("accepting a roleplay turn", () => {
  it("brackets a multi-paragraph reply as one beat, its interiority stored once", async () => {
    const { editor, ctrl } = await setup();
    fakeStream("She fired.\n\nThen ran.[[interiority]]Steady now.");
    await ctrl.runPromptEntryWithInputs(ROLEPLAY, { character: ELIAS });
    ctrl.accept();
    const { beats, orphans } = scanBeats(editor.state.doc);
    expect(orphans).toEqual([]);
    expect(beats).toHaveLength(1);
    expect(beats[0]).toMatchObject({ characterId: "lore_elias", internal: "Steady now." });
    expect(editorHtmlToSceneMarkdown(editor.getHTML())).toBe(
      "<!-- character:id=lore_elias -->She fired.\n\nThen ran.<!-- /character:id=lore_elias;internal=Steady%20now. -->",
    );
  });
});

describe("a roleplay turn inside a beat", () => {
  it("is refused with the reason, and nothing is sent", async () => {
    const { editor, ctrl, notices } = await setup(
      "<!-- character:id=lore_elias -->She fired.<!-- /character:id=lore_elias;internal=Steady. -->",
    );
    editor.commands.setTextSelection(4);
    const stream = fakeStream("Again.");
    await ctrl.runPromptEntryWithInputs(ROLEPLAY, { character: ELIAS });
    expect(stream).not.toHaveBeenCalled();
    expect(notices).toEqual(["Inside Elias's beat: move the cursor outside it, or split the beat."]);
  });
});

describe("a roleplay reply whose cursor moved into a beat during the call", () => {
  it("is not placed there", async () => {
    const { editor, ctrl } = await setup(
      "Narration.\n\n<!-- character:id=lore_elias -->She fired.<!-- /character:id=lore_elias;internal=Steady. -->",
    );
    editor.commands.setTextSelection(2); // in the narration: the send is allowed
    vi.spyOn(api, "aiGenerateStream").mockImplementation(async function* () {
      // Before the first token arrives, the author clicks inside the beat.
      editor.commands.setTextSelection(editor.state.doc.child(0).nodeSize + 4);
      yield { type: "delta", text: "Again." } as never;
      yield { type: "done", provider: "p", model: "m", latency_ms: 1, truncated: false } as never;
    });
    await ctrl.runPromptEntryWithInputs(ROLEPLAY, { character: ELIAS });
    expect(ctrl.suggestionId).toBeNull();
    expect(ctrl.error).toMatch(/moved into a beat/);
    expect(editor.state.doc.textContent).not.toContain("Again.");
  });
});
