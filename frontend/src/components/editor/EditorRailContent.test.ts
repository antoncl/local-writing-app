// @vitest-environment happy-dom
// EditorRailContent (#2029 follow-up; Conversations and Mutation sets moved
// to body tabs in ADR-0089 Amendment 1 §4, #2101; References — the outgoing
// related_entries list AND the BacklinksPanel — moved to the merged
// "References" body tab in slice C3, so this rail no longer renders
// BacklinksPanel at all): a smoke test only — MetadataPanel mounts fine
// under happy-dom. `scene: null` here keeps this test network-free (the
// #973 network guard other rail tests dodge the same way) while still
// proving the rail's own wiring — the type head and the trailing snippet
// (now just MutationTimeline, lore-scoped) — renders through the new
// `{ model, deps, on }` seam.
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
    "lore:note": { name: "Note", kind: "lore", parent: "lore:base", fields: ["remark"] },
  },
  fields: {
    remark: { name: "Remark", type: "text", options: [] },
  },
} as unknown as MetadataSchema;

const DOCUMENT_ENTRY_TYPES = [
  ["lore:base", SCHEMA.entry_types["lore:base"]],
  ["lore:note", SCHEMA.entry_types["lore:note"]],
] as never;

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});

describe("EditorRailContent", () => {
  it("renders the type head with no scene open", () => {
    renderRail();
    expect(document.querySelector(".rail-type")).not.toBeNull();
    expect(screen.getByText("Note")).toBeInTheDocument();
  });

  it("the empty-field fold renders inside the metadata panel (#2037)", () => {
    // `remark` is empty, so the fold renders. With no scene open the
    // trailing MutationTimeline doesn't mount either (lore-scoped on
    // `model.scene?.id` — References/BacklinksPanel moved out to the body
    // tab strip entirely in ADR-0089 Amendment 1 §4 slice C3, #2101), so
    // this only proves the fold's own placement now.
    renderRail();
    const fold = document.querySelector('[data-testid="rail-fold-toggle"]') as HTMLElement;
    expect(fold).not.toBeNull();
    expect(fold.closest(".scene-metadata")).not.toBeNull();
  });

  it("`facts` renders the rows as front matter with no trailing sections (#2054)", () => {
    renderRail("facts");
    expect(document.querySelector(".scene-metadata.front-matter")).not.toBeNull();
    expect(document.querySelector('[data-testid="rail-appendix"]')).toBeNull();
  });

  it("`trailing` renders the appendix with no metadata rows (#2054)", () => {
    // References (Related Entries + BacklinksPanel) moved to the body tab
    // strip (slice C3); with no scene open the lore-only MutationTimeline
    // doesn't mount, so the appendix is empty here — this only proves the
    // `part="trailing"` slot boundary (no `.scene-metadata`).
    renderRail("trailing");
    expect(document.querySelector(".scene-metadata")).toBeNull();
    expect(document.querySelector('[data-testid="rail-appendix"]')).not.toBeNull();
  });

  function renderRail(part: "rail" | "facts" | "trailing" = "rail") {
    render(EditorRailContent, {
      part,
      model: {
        metadataSchema: SCHEMA,
        entryType: "lore:note",
        status: "",
        metadata: {},
        documentKind: "lore",
        documentLabel: "Entry",
        documentEntryTypes: DOCUMENT_ENTRY_TYPES,
        metadataFieldIds: ["remark"],
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
        goToList: () => {},
        park: () => {},
      },
    });
  }
});
