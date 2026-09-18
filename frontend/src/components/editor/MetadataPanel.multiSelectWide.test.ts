// @vitest-environment happy-dom
// #1949 — an option-less `multi_select` (e.g. the built-in Aliases) is a
// freeform value list edited/shown as one bare <input>. Compact, its value
// was clipped in the narrow right-anchored value column. It now follows the
// same "wide when populated" rule as `entity_ref_list` (#1810): a value drops
// to its own full-width line (visible in full, at rest and while editing),
// while an empty one stays a compact single row. A multi_select WITH options
// renders chips and is wide unconditionally.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: ["aliases", "traits"] },
  },
  fields: {
    aliases: { name: "Aliases", type: "multi_select", options: [] },
    traits: {
      name: "Traits",
      type: "multi_select",
      options: [
        { value: "brave", label: "Brave" },
        { value: "sly", label: "Sly" },
      ],
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
      metadataFieldIds: ["aliases", "traits"],
      onMetadataChange: vi.fn(),
    },
  });
}

function rowFor(label: string): HTMLElement {
  const row = screen.getByText(label).closest(".field-row");
  if (!row) throw new Error(`no .field-row ancestor for "${label}"`);
  return row as HTMLElement;
}

describe("MetadataPanel — option-less multi_select goes wide when populated (#1949)", () => {
  it("an option-less multi_select with a value IS .wide — the value gets its own full-width line", () => {
    mount({ aliases: ["Little Myrrh", "Myrrh", "The Inheritor"] });
    expect(rowFor("Aliases").classList.contains("wide")).toBe(true);
  });

  it("an empty option-less multi_select is NOT .wide — one compact row, like an empty ref list", async () => {
    mount({ aliases: [] });
    // #2006: an empty aliases row now folds by default — open it first.
    await fireEvent.click(screen.getByTestId("rail-fold-toggle"));
    expect(rowFor("Aliases").classList.contains("wide")).toBe(false);
  });

  it("an unset (absent-key) option-less multi_select is NOT .wide either", async () => {
    mount({});
    // #2006: an unset aliases row now folds by default — open it first.
    await fireEvent.click(screen.getByTestId("rail-fold-toggle"));
    expect(rowFor("Aliases").classList.contains("wide")).toBe(false);
  });

  it("a multi_select WITH options is .wide unconditionally — it renders chips, never a bare add control", async () => {
    mount({});
    // #2006: an unset traits row now folds by default — open it first.
    await fireEvent.click(screen.getByTestId("rail-fold-toggle"));
    expect(rowFor("Traits").classList.contains("wide")).toBe(true);
  });
});
