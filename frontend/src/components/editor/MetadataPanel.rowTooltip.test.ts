// @vitest-environment happy-dom
// #1900 — a field's description is the tooltip of its name AND of its at-rest
// value control (the thing the author is about to change). A field without a
// description keeps the control's plain "Set / Edit <name>" title.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const REACH = "How far the app reaches for lore it adds on its own.";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:note": { name: "Note", kind: "lore", fields: ["reach", "alias"] } },
  fields: {
    reach: {
      name: "Lore reach",
      description: REACH,
      type: "select",
      default: "one_hop",
      options: [
        { value: "one_hop", label: "One hop" },
        { value: "named", label: "Named only" },
      ],
    },
    alias: { name: "Alias", type: "text" },
  },
} as unknown as MetadataSchema;

beforeEach(() => metadataSchemaStore.set(SCHEMA));

function mount(metadata: EntryMetadata) {
  render(MetadataPanel, {
    props: {
      entryType: "lore:note",
      status: "",
      metadata,
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:note", SCHEMA.entry_types["lore:note"]]] as never,
      metadataFieldIds: ["reach", "alias"],
      onMetadataChange: vi.fn(),
    },
  });
}

function rowFor(label: string): HTMLElement {
  const row = screen.getByText(label).closest(".field-row");
  if (!row) throw new Error(`no .field-row ancestor for "${label}"`);
  return row as HTMLElement;
}

describe("MetadataPanel — the description is the name's and the control's tooltip (#1900)", () => {
  it("a described field: the name and the at-rest control both carry the description; the row does not", () => {
    mount({});
    const row = rowFor("Lore reach");
    expect(screen.getByText("Lore reach").getAttribute("title")).toBe(REACH);
    expect(row.querySelector(".fr-rest-hit")?.getAttribute("title")).toBe(REACH);
    expect(row.hasAttribute("title")).toBe(false);
  });

  it("a field without a description: no title on the name; the control keeps its plain verb", () => {
    mount({});
    const row = rowFor("Alias");
    expect(screen.getByText("Alias").hasAttribute("title")).toBe(false);
    expect(row.querySelector(".fr-rest-hit")?.getAttribute("title")).toBe("Set Alias");
  });

  it("a select with a default shows the default at rest, not (none)", () => {
    mount({});
    const row = rowFor("Lore reach");
    expect(row.textContent).toContain("One hop");
    expect(row.textContent).not.toContain("(none)");
  });
});
