// @vitest-environment happy-dom
// #2475: inline prompts honour `offer_on`, so a lore entry body runs a
// lore-offered line-edit prompt. Real TipTap editor + the real controller; only
// `api` is faked.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Editor } from "@tiptap/core";
import { api } from "@/lib/api";
import { proseStarterKit } from "./proseStarterKit";
import { AiSuggestionController } from "./aiSuggestion.svelte";
import { LineEditSuggestions, acceptLineEdit, lineEditState } from "./lineEditSuggestions";
import type { DocumentKind } from "@/lib/types";

const editors: Editor[] = [];
beforeEach(() => {
  vi.spyOn(api, "aiAppendInvocation").mockResolvedValue(undefined as never);
});
afterEach(() => {
  vi.restoreAllMocks();
  for (const editor of editors.splice(0)) editor.destroy();
});

const SCHEMA = {
  entry_types: { "manuscript:scene": {}, "lore:base": {}, "lore:character": { parent: "lore:base" } },
  fields: {},
};
const strategy = { output: { handler: "inline_edits" } };
const LORE_P = {
  id: "p_lore",
  title: "Line edit (entry)",
  body: "x",
  entry_type: "prompt:general",
  offer_on: ["lore:base"],
  inputs: [{ name: "entry", type: "context_pick", label: "Entry", hidden: true }],
  context_strategy: strategy,
} as never;
const SCENE_P = {
  id: "p_scene",
  title: "Line edit",
  body: "x",
  entry_type: "prompt:general",
  offer_on: ["manuscript:scene"],
  inputs: [],
  context_strategy: strategy,
} as never;
const VISIBLE_P = {
  id: "p_vis",
  title: "With lore",
  body: "x",
  entry_type: "prompt:general",
  offer_on: ["manuscript:scene"],
  inputs: [{ name: "lore", type: "context_pick", label: "Lore" }],
  context_strategy: strategy,
} as never;

function setup(kind: DocumentKind, doc: { id: string; title: string; entry_type: string }) {
  const editor = new Editor({
    element: document.createElement("div"),
    extensions: [proseStarterKit(), LineEditSuggestions],
    content: { type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: "The cat sat." }] }] },
  });
  editors.push(editor);
  editor.commands.setTextSelection({ from: 1, to: editor.state.doc.content.size - 1 });
  const notices: string[] = [];
  const dialogs: Array<{ prefilledDrafts?: Record<string, string> }> = [];
  const ctrl = new AiSuggestionController({
    getEditor: () => editor,
    getEditorFrame: () => undefined,
    getScene: () => doc as never,
    getDocumentKind: () => kind,
    getPromptCtx: () => ({ metadataSchema: SCHEMA, promptEntries: [LORE_P, SCENE_P, VISIBLE_P] }) as never,
    onInvocationCost: () => {},
    addCharacterCost: () => {},
    onRequestInputsDialog: (p) => dialogs.push(p),
    onNotice: (m) => notices.push(m),
    onOpenChat: () => {},
  });
  return { editor, ctrl, notices, dialogs };
}

const reply = (edits: unknown[] = []) =>
  ({ ok: true, content: "", provider: "p", model: "m", latency_ms: 1, truncated: false, cost_usd: 0.01, edits }) as never;
const LORE_DOC = { id: "lore_1", title: "Irene", entry_type: "lore:character" };
const SCENE_DOC = { id: "scene_1", title: "Opening", entry_type: "manuscript:scene" };

describe("inline prompts on a lore document (#2475)", () => {
  it("runs a lore-offered prompt with no dialog, entry seeded, no target scene", async () => {
    const { ctrl, dialogs } = setup("lore", LORE_DOC);
    const spy = vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
    await ctrl.runPromptEntry(LORE_P);
    expect(dialogs).toEqual([]);
    const req = spy.mock.calls[0][0];
    expect(req.target_scene_id).toBe("");
    expect(req.session_id).toBe("lore_1");
    expect(req.inputs?.entry).toEqual([
      { id: "lore_1", kind: "lore", title: "Irene", entry_type: "lore:character" },
    ]);
  });

  it("refuses a scene-only prompt with a notice", async () => {
    const { ctrl, notices } = setup("lore", LORE_DOC);
    const spy = vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
    await ctrl.runPromptEntry(SCENE_P);
    expect(spy).not.toHaveBeenCalled();
    expect(notices).toHaveLength(1);
  });

  it("files telemetry under no scene", async () => {
    const { editor, ctrl } = setup("lore", LORE_DOC);
    vi.spyOn(api, "aiGenerate").mockResolvedValue(reply([{ find: "cat", replace: "dog", reason: "r" }]));
    await ctrl.runPromptEntry(LORE_P);
    acceptLineEdit(editor.view, lineEditState(editor.state).edits[0].id);
    expect(api.aiAppendInvocation).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.aiAppendInvocation).mock.calls[0][0].scene_id).toBe("");
  });
});

describe("inline prompts on a scene are unchanged (#2475)", () => {
  it("sends the scene id and runs a no-input prompt directly", async () => {
    const { ctrl, dialogs } = setup("manuscript", SCENE_DOC);
    const spy = vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
    await ctrl.runPromptEntry(SCENE_P);
    expect(dialogs).toEqual([]);
    expect(spy.mock.calls[0][0].target_scene_id).toBe("scene_1");
    expect(spy.mock.calls[0][0].inputs).toEqual({});
  });

  it("still opens the dialog for a prompt with a visible input", async () => {
    const { ctrl, dialogs } = setup("manuscript", SCENE_DOC);
    const spy = vi.spyOn(api, "aiGenerate").mockResolvedValue(reply());
    await ctrl.runPromptEntry(VISIBLE_P);
    expect(spy).not.toHaveBeenCalled();
    expect(dialogs).toHaveLength(1);
  });
});
