// isEditorPaneDirty's inputs arm (#1470). The editor emits a MINIMAL canonical
// input (`toCanonical`); the server saves it and echoes back the model's filled
// defaults (`hidden`, `required: false`, an empty picker `options`). A raw
// JSON compare of the draft against that echo is perpetually unequal, so a
// context_pick prompt would autosave itself every few seconds with no edits.
// The dirty-check canonicalizes both sides first; these lock that in.
import { describe, expect, it } from "vitest";
import { isEditorPaneDirty } from "./editorPaneModel";
import type { EditableDocument, PromptInputDefinition } from "@/lib/types";

const target = { sources: [{ kind: "lore" }], presets: [] };

// The server's saved-and-echoed shape: the draft's minimal fields PLUS the
// model defaults the editor never sends.
function promptScene(
  extraInputFields: Record<string, unknown> = { options: [], required: false, hidden: false },
): EditableDocument {
  return {
    id: "prompt_1",
    title: "General chat",
    body: "b",
    entry_type: "prompt:general",
    metadata: {},
    inputs: [{ name: "lore", type: "context_pick", label: "Lore", target, ...extraInputFields }],
  } as unknown as EditableDocument;
}

// The unchanged non-inputs args, so only the inputs param varies below.
const base = (scene: EditableDocument) =>
  [scene, scene.title, scene.body ?? "", "", scene.entry_type, {}] as const;

// What the editor holds as the live draft: the minimal canonical form.
const draftInputs: PromptInputDefinition[] = [
  { name: "lore", type: "context_pick", label: "Lore", target } as unknown as PromptInputDefinition,
];

describe("isEditorPaneDirty — inputs (#1470)", () => {
  it("is CLEAN when the draft equals the server echo modulo filled defaults", () => {
    // The regression: without canonicalization this returns true forever.
    expect(isEditorPaneDirty(...base(promptScene()), draftInputs)).toBe(false);
  });

  it("is clean even if the server omits the defaults entirely", () => {
    expect(isEditorPaneDirty(...base(promptScene({})), draftInputs)).toBe(false);
  });

  it("is dirty when an input's label actually changes", () => {
    const edited: PromptInputDefinition[] = [
      { name: "lore", type: "context_pick", label: "Lore entries", target } as unknown as PromptInputDefinition,
    ];
    expect(isEditorPaneDirty(...base(promptScene()), edited)).toBe(true);
  });

  it("is dirty when an input is added", () => {
    const edited: PromptInputDefinition[] = [
      ...draftInputs,
      { name: "tone", type: "text", label: "Tone" } as unknown as PromptInputDefinition,
    ];
    expect(isEditorPaneDirty(...base(promptScene()), edited)).toBe(true);
  });

  it("is dirty when inputs are reordered (order is significant)", () => {
    const scene = {
      ...promptScene({}),
      inputs: [
        { name: "a", type: "text", label: "A" },
        { name: "b", type: "text", label: "B" },
      ],
    } as unknown as EditableDocument;
    const reordered: PromptInputDefinition[] = [
      { name: "b", type: "text", label: "B" } as unknown as PromptInputDefinition,
      { name: "a", type: "text", label: "A" } as unknown as PromptInputDefinition,
    ];
    expect(isEditorPaneDirty(...base(scene), reordered)).toBe(true);
  });

  it("keeps a real boolean default:false (not stripped as noise)", () => {
    // A generic 'drop falsy keys' fix would erase this; canonicalization keeps
    // it because the editor genuinely emits default:false for it.
    const scene = {
      ...promptScene({}),
      inputs: [{ name: "flag", type: "boolean", label: "Flag", default: false }],
    } as unknown as EditableDocument;
    const draftUnset: PromptInputDefinition[] = [
      { name: "flag", type: "boolean", label: "Flag" } as unknown as PromptInputDefinition,
    ];
    // Draft has no default; scene has default:false → a real difference → dirty.
    expect(isEditorPaneDirty(...base(scene), draftUnset)).toBe(true);
  });

  it("never marks a non-prompt pane dirty (no inputs baseline)", () => {
    const lore = {
      id: "lore_1",
      title: "Hero",
      body: "b",
      entry_type: "lore:character",
      metadata: {},
    } as unknown as EditableDocument;
    expect(isEditorPaneDirty(lore, lore.title, "b", "", lore.entry_type, {}, draftInputs)).toBe(false);
  });
});
