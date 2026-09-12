// @vitest-environment happy-dom
// #1884 slice 3 — an empty row recedes: `.field-row.empty` when the field
// carries no value. `color` always shows an effective (placeholder) swatch,
// so it never reads empty.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: ["alias", "tone", "hue", "kin"] } },
  fields: {
    alias: { name: "Alias", type: "text" },
    tone: {
      name: "Tone",
      type: "select",
      options: [
        { value: "warm", label: "Warm" },
        { value: "cool", label: "Cool" },
      ],
    },
    hue: { name: "Hue", type: "color" },
    kin: {
      name: "Kin",
      type: "entity_ref_list",
      options: [],
      picker_config: { sources: [{ kind: "lore" }] },
    },
  },
} as unknown as MetadataSchema;

beforeEach(() => metadataSchemaStore.set(SCHEMA));

function mount(metadata: EntryMetadata) {
  render(MetadataPanel, {
    props: {
      entryType: "lore:character",
      status: "",
      metadata,
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:character", SCHEMA.entry_types["lore:character"]]] as never,
      metadataFieldIds: ["alias", "tone", "hue", "kin"],
      onMetadataChange: vi.fn(),
    },
  });
}

function rowFor(label: string): HTMLElement {
  const row = screen.getByText(label).closest(".field-row");
  if (!row) throw new Error(`no .field-row ancestor for "${label}"`);
  return row as HTMLElement;
}

describe("MetadataPanel — empty rows recede (#1884 slice 3)", () => {
  it("empty metadata: alias, tone, kin are .empty; hue is not (always an effective swatch)", () => {
    mount({});
    expect(rowFor("Alias").classList.contains("empty")).toBe(true);
    expect(rowFor("Tone").classList.contains("empty")).toBe(true);
    expect(rowFor("Kin").classList.contains("empty")).toBe(true);
    expect(rowFor("Hue").classList.contains("empty")).toBe(false);
  });

  it("a set value loses .empty; an unset sibling keeps it", () => {
    mount({ alias: "The Painted", kin: ["lore_1"] });
    expect(rowFor("Alias").classList.contains("empty")).toBe(false);
    expect(rowFor("Kin").classList.contains("empty")).toBe(false);
    expect(rowFor("Tone").classList.contains("empty")).toBe(true);
  });
});
