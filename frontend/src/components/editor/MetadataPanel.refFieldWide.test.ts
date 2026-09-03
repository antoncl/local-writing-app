// @vitest-environment happy-dom
// #1810 — an EMPTY `entity_ref_list` (Tags, Related Entries) used to render
// wide (the rail's `.field-row.wide`), which stretches its lone "+" add
// trigger into its own left-aligned line — two rows, asymmetric with an empty
// `entity_ref` (Home Place), which stays a single compact row with the "+" at
// the right. `isWide` (MetadataPanel.svelte) now only counts an
// `entity_ref_list` as wide once its value actually holds something to wrap;
// empty, it renders exactly like an empty `entity_ref` — one row, `.field-row`
// without `.wide`.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: ["allies"] } },
  fields: {
    allies: {
      name: "Allies",
      type: "entity_ref_list",
      options: [],
      picker_config: { sources: [{ kind: "lore" }] },
    },
  },
} as unknown as MetadataSchema;

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});

function mount(metadata: EntryMetadata) {
  render(MetadataPanel, {
    props: {
      entryType: "lore:character",
      status: "",
      metadata,
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:character", SCHEMA.entry_types["lore:character"]]] as never,
      metadataFieldIds: ["allies"],
      onMetadataChange: vi.fn(),
    },
  });
}

function rowFor(label: string): HTMLElement {
  const row = screen.getByText(label).closest(".field-row");
  if (!row) throw new Error(`no .field-row ancestor for "${label}"`);
  return row as HTMLElement;
}

describe("MetadataPanel — empty entity_ref_list renders compact, not wide (#1810)", () => {
  it("an empty entity_ref_list is NOT .wide — one row, like an empty entity_ref", () => {
    mount({ allies: [] });
    expect(rowFor("Allies").classList.contains("wide")).toBe(false);
  });

  it("a non-empty entity_ref_list IS .wide — the pills get their own wrapping line", () => {
    mount({ allies: ["lore_1"] });
    expect(rowFor("Allies").classList.contains("wide")).toBe(true);
  });

  it("an unset (absent-key) entity_ref_list is NOT .wide either", () => {
    mount({});
    expect(rowFor("Allies").classList.contains("wide")).toBe(false);
  });
});
