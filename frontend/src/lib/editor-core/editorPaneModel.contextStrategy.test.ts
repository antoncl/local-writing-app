// isEditorPaneDirty's context_strategy arm (ADR-0065 S3 / ADR-0062 D3). Editing
// the output-config draft (mode/headless/commit) must arm autosave the same way
// editing offer_on/inputs does — and, like those, must never mark a non-prompt
// pane dirty (no context_strategy baseline).
import { describe, expect, it } from "vitest";
import { isEditorPaneDirty } from "./editorPaneModel";
import type { EditableDocument, PromptContextStrategy } from "@/lib/types";

function promptScene(contextStrategy: PromptContextStrategy | null): EditableDocument {
  return {
    id: "prompt_1",
    title: "Summarize",
    body: "brief",
    entry_type: "prompt:general",
    metadata: {},
    inputs: [],
    offer_on: [],
    context_strategy: contextStrategy,
  } as unknown as EditableDocument;
}

// The unchanged non-context_strategy args, so only the last param varies below.
const base = (scene: EditableDocument) =>
  [scene, scene.title, scene.body ?? "", "", scene.entry_type, {}, undefined, undefined] as const;

describe("isEditorPaneDirty — context_strategy (ADR-0062 D3)", () => {
  it("is clean when the draft equals the baseline (both null)", () => {
    const scene = promptScene(null);
    expect(isEditorPaneDirty(...base(scene), null)).toBe(false);
  });

  it("is clean when the draft deep-equals a non-null baseline", () => {
    const strategy: PromptContextStrategy = { output: { handler: "inline", destination: "cursor" } };
    const scene = promptScene(strategy);
    expect(isEditorPaneDirty(...base(scene), { output: { handler: "inline", destination: "cursor" } })).toBe(false);
  });

  it("is dirty when the mode changes", () => {
    const scene = promptScene({ output: { handler: "inline" } });
    expect(isEditorPaneDirty(...base(scene), { output: { handler: "extract_to_node" } })).toBe(true);
  });

  it("is dirty when headless toggles", () => {
    const scene = promptScene({ output: { handler: "extract_to_node" } });
    expect(isEditorPaneDirty(...base(scene), { output: { handler: "extract_to_node", headless: true } })).toBe(true);
  });

  it("is dirty when the draft clears an authored baseline", () => {
    const scene = promptScene({ output: { handler: "inline" } });
    expect(isEditorPaneDirty(...base(scene), null)).toBe(true);
  });

  it("never marks a non-prompt pane dirty (no context_strategy baseline)", () => {
    const lore = {
      id: "lore_1",
      title: "Hero",
      body: "b",
      entry_type: "lore:character",
      metadata: {},
    } as unknown as EditableDocument;
    // A non-prompt scene has no context_strategy; the store still passes the
    // pane's draftContextStrategy, which must be inert here.
    expect(
      isEditorPaneDirty(lore, lore.title, "b", "", lore.entry_type, {}, undefined, undefined, {
        output: { handler: "inline" },
      }),
    ).toBe(false);
  });
});
