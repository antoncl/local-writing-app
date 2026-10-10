// @vitest-environment happy-dom
// #2438: the rail's undo wiring through EditorRailContent — a rail change
// reaches the controller (as NodeEditor's `metadataChange` records it), focus
// that fell to <body> returns to the rail's chord scope, Ctrl+Z on that scope
// reverses the change, and an unrelated re-render never pulls focus.
import { beforeEach, describe, expect, it } from "vitest";
import { tick } from "svelte";
import { fireEvent, render, screen } from "@/lib/test/component";
import EditorRailContent from "./EditorRailContent.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { createSectionRegistry } from "@/lib/editor-core/sectionKeyboardBridge";
import { LoreScrubController } from "@/lib/stores/loreScrub.svelte";
import { RailUndoController } from "@/lib/rail/railUndoController.svelte";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:note": { name: "Note", kind: "lore", fields: ["remark"] } },
  fields: { remark: { name: "Remark", type: "text", options: [] } },
} as unknown as MetadataSchema;

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
  (document.activeElement as HTMLElement | null)?.blur?.();
});

async function settle() {
  await tick();
  await tick();
  await Promise.resolve();
}

function mount(initial: EntryMetadata) {
  const state = { metadata: initial };
  const railUndo = new RailUndoController({
    getMetadata: () => state.metadata,
    applyMetadata: (next) => (state.metadata = next),
    getStatus: () => "",
    applyStatus: () => {},
    fieldLabel: (id) => id,
    locked: () => false,
  });
  const model = (title: string) => ({
    metadataSchema: SCHEMA,
    entryType: "lore:note",
    status: "",
    metadata: state.metadata,
    documentKind: "lore",
    documentLabel: "Entry",
    documentEntryTypes: [["lore:note", SCHEMA.entry_types["lore:note"]]],
    metadataFieldIds: ["remark"],
    scene: null,
    createLayerId: null,
    overriddenFieldsForPanel: [],
    scrubbed: false,
    scrub: new LoreScrubController(),
    stopUnit: null,
    compare: null,
    editorReadOnly: false,
    bodyShape: "none",
    resolvedCascade: null,
    backlinks: [],
    title,
    hostPaneId: null,
    railUndo,
  });
  const props = (title: string) => ({
    model: model(title),
    deps: {
      loreEntries: [],
      promptEntries: [],
      structure: null,
      researchStructure: null,
      implicitContextMatcher: null,
      sectionRegistry: createSectionRegistry(),
      computedFieldString: () => "",
    },
    on: {
      entryTypeChange: () => {},
      statusChange: () => {},
      // What NodeEditor's rail `metadataChange` does.
      metadataChange: (next: EntryMetadata, session?: string) => {
        railUndo.recordMetadata(state.metadata, next, session);
        state.metadata = next;
      },
      customData: () => {},
      navigate: () => {},
      resetField: () => {},
      goToSection: () => {},
      goToList: () => {},
      park: () => {},
    },
  });
  const { rerender } = render(EditorRailContent, props("A") as never);
  return { state, railUndo, rerender: (title: string) => rerender(props(title) as never) };
}

describe("EditorRailContent — rail undo wiring (#2438)", () => {
  it("a rail clear records, focus returns to the scope, and Ctrl+Z there restores it", async () => {
    const { state, railUndo } = mount({ remark: "hi" });
    await fireEvent.click(screen.getByRole("button", { name: "Reset Remark to default" }));
    expect(state.metadata).toEqual({});
    expect(railUndo.canUndo).toBe(true);

    await settle();
    const scope = document.querySelector(".rail-undo-scope") as HTMLElement;
    expect(document.activeElement).toBe(scope);

    await fireEvent.keyDown(scope, { key: "z", ctrlKey: true });
    await settle();
    expect(state.metadata).toEqual({ remark: "hi" });
  });

  it("an unrelated re-render does not pull focus into the rail", async () => {
    const { rerender } = mount({ remark: "hi" });
    await fireEvent.click(screen.getByRole("button", { name: "Reset Remark to default" }));
    await settle();
    (document.activeElement as HTMLElement).blur();
    expect(document.activeElement).toBe(document.body);

    await rerender("B"); // a title change: model rebuilt, nothing recorded
    await settle();
    expect(document.activeElement).toBe(document.body);
  });
});
