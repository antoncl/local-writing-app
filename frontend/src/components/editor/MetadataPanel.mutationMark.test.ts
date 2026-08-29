// @vitest-environment happy-dom
// #492: the `⤳` mutation mark is co-located with the value, not split onto the
// field-name cell. design-language.md §marks — "Provenance leads the value;
// mutation trails it" — so an overridden+mutated field reads `[versions] Captain ⤳`
// on one line. This guards the mark rendering inside `.fr-val`, never `.fr-name`.
import { beforeEach, describe, expect, it } from "vitest";
import { render } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: ["rank"] } },
  fields: {
    rank: { name: "Rank", type: "text" },
  },
} as unknown as MetadataSchema;

beforeEach(() => metadataSchemaStore.set(SCHEMA));

function mount(metadata: EntryMetadata, effectiveOverrides: Record<string, string> | null) {
  const { container } = render(MetadataPanel, {
    props: {
      entryType: "lore:character",
      status: "",
      metadata,
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:character", SCHEMA.entry_types["lore:character"]]] as never,
      metadataFieldIds: ["rank"],
      effectiveOverrides,
    },
  });
  return container;
}

describe("MetadataPanel — mutation mark trails the value (#492)", () => {
  it("renders the `⤳` mark inside the value cell, not the name cell", () => {
    const container = mount({ rank: "Captain" }, { rank: "Captain" });

    // The mark exists...
    const mark = container.querySelector(".fr-mutated-marker");
    expect(mark).not.toBeNull();
    expect(mark?.textContent).toContain("⤳");

    // ...co-located with the value (trails it), never on the field name.
    expect(container.querySelector(".fr-val .fr-mutated-marker")).not.toBeNull();
    expect(container.querySelector(".fr-name .fr-mutated-marker")).toBeNull();
  });

  it("omits the mark on an unmutated field", () => {
    const container = mount({ rank: "Captain" }, null);
    expect(container.querySelector(".fr-mutated-marker")).toBeNull();
  });
});
