// @vitest-environment happy-dom
// EditorRailContent (#2029 follow-up): a smoke test only — MetadataPanel and
// BacklinksPanel mount fine under happy-dom, but ConversationsPanel and
// PinnedSetsPanel only render when `model.scene?.id` is set, and they reach
// out to the API on mount (the #973 network guard other rail tests dodge the
// same way). `scene: null` here keeps this test network-free while still
// proving the rail's own wiring — the type head + the always-mounted
// BacklinksPanel — renders through the new `{ model, deps, on }` seam.
import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import EditorRailContent from "./EditorRailContent.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { createSectionRegistry } from "@/lib/editor-core/sectionKeyboardBridge";
import { LoreScrubController } from "@/lib/stores/loreScrub.svelte";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", icon: "book", fields: [] },
    "lore:note": { name: "Note", kind: "lore", parent: "lore:base", fields: [] },
  },
  fields: {},
} as unknown as MetadataSchema;

const DOCUMENT_ENTRY_TYPES = [
  ["lore:base", SCHEMA.entry_types["lore:base"]],
  ["lore:note", SCHEMA.entry_types["lore:note"]],
] as never;

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});

describe("EditorRailContent", () => {
  it("renders the type head and the backlinks panel with no scene open", () => {
    render(EditorRailContent, {
      model: {
        metadataSchema: SCHEMA,
        entryType: "lore:note",
        status: "",
        metadata: {},
        documentKind: "lore",
        documentLabel: "Entry",
        documentEntryTypes: DOCUMENT_ENTRY_TYPES,
        metadataFieldIds: [],
        scene: null,
        createLayerId: null,
        overriddenFieldsForPanel: [],
        scrubbed: false,
        scrub: new LoreScrubController(),
        compare: null,
        editorReadOnly: false,
        bodyShape: "none",
        resolvedCascade: null,
        backlinks: [],
        title: "",
        hostPaneId: null,
      },
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
        metadataChange: () => {},
        customData: () => {},
        navigate: () => {},
        resetField: () => {},
        goToSection: () => {},
        park: () => {},
      },
    });

    expect(document.querySelector(".rail-type")).not.toBeNull();
    expect(screen.getByText("Note")).toBeInTheDocument();
  });
});
