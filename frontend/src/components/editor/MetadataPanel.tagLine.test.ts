// @vitest-environment happy-dom
// #2007 — MetadataPanel routes a tag-vocabulary `entity_ref_list` (ADR-0082's
// single-kind-`tag` carve-out) to RailTagLine, never the generic ref-pill
// picker: the tags row carries RailTagLine's own testid and neither a
// `.ref-pill` nor the folding-list gutter caret, while an ordinary lore
// `entity_ref_list` (`kin`) is untouched — still pills, still a caret once
// populated.
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { clearTagNodes, tagNodesStore } from "@/lib/stores/tagNodes";
import type { LoreEntrySummary, MetadataSchema, TagEntry } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: ["tags", "kin"] },
    "tag:theme": { name: "Theme", kind: "tag" },
  },
  fields: {
    tags: {
      name: "Tags",
      type: "entity_ref_list",
      options: [],
      picker_config: {
        sources: [{ kind: "tag", expr: { type: "tag:theme" } }],
        create_missing: true,
      },
    },
    kin: {
      name: "Kin",
      type: "entity_ref_list",
      options: [],
      picker_config: { sources: [{ kind: "lore" }] },
    },
  },
} as unknown as MetadataSchema;

const TAGS: TagEntry[] = [
  { id: "tag_a", title: "Alpha", entry_type: "tag:theme", metadata: {} },
  { id: "tag_b", title: "Beta", entry_type: "tag:theme", metadata: {} },
];

const loreEntries = [{ id: "lore_1", title: "Mira", entry_type: "lore:character" }] as unknown as LoreEntrySummary[];

function mount() {
  render(MetadataPanel, {
    props: {
      entryType: "lore:character",
      status: "",
      metadata: { tags: ["tag_a", "tag_b"], kin: ["lore_1"] },
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:character", SCHEMA.entry_types["lore:character"]]] as never,
      metadataFieldIds: ["tags", "kin"],
      loreEntries,
      onMetadataChange: vi.fn(),
    },
  });
}

// Cleared, not nulled: MetadataPanel derives `metadataSchema` non-null from
// this store (it only ever mounts inside NodeEditor's `{#if metadataSchema}`
// guard) — nulling it after a test can outrace `cleanup()`'s unmount and
// throw from a still-settling reactive read (matches the other MetadataPanel
// fixtures, which never null the schema store either).
afterEach(() => {
  clearTagNodes();
});

describe("MetadataPanel — a tags field routes to RailTagLine, not pills (#2007)", () => {
  it("the tags row carries rail-tag-line and no ref-pill / no gutter caret", () => {
    metadataSchemaStore.set(SCHEMA);
    tagNodesStore.set(TAGS);
    mount();

    const tagsRow = screen.getByTestId("rail-tag-line").closest(".field-row");
    expect(tagsRow).not.toBeNull();
    expect(tagsRow?.querySelector(".ref-pill")).toBeNull();
    expect(tagsRow?.querySelector(".fr-disc-toggle")).toBeNull();
  });

  it("an ordinary populated lore ref list (kin) still gets the gutter caret", () => {
    metadataSchemaStore.set(SCHEMA);
    tagNodesStore.set(TAGS);
    mount();

    const kinRow = screen.getByText("Kin").closest(".field-row");
    expect(kinRow?.querySelector(".fr-disc-toggle")).toBeInTheDocument();
  });
});
