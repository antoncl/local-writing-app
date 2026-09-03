// @vitest-environment happy-dom
// #1797 (round 2, Y7) — the tag-vocabulary flip candidate's own chip strip,
// extracted from MetadataPanel. A known id renders its title as an ordinary
// chip; a still-unresolved title (the validator never mints at validation —
// ADR-0082 §2) renders as a distinct "new tag" pill (round 2, Y5 — a
// separate pill element, never a `+ ` text prefix, so a title that itself
// starts with a symbol/digit like "+1" can't misread as part of the marker).
import { describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import TagFlipChips, { isTagFlipField, tagFlipItemsFor } from "./TagFlipChips.svelte";
import type { MetadataFieldDefinition, MetadataSchema } from "@/lib/types";

describe("TagFlipChips — render", () => {
  it("renders a known id as an ordinary chip, titled and testid'd", () => {
    render(TagFlipChips, {
      props: { items: [{ key: "tag_1", label: "Old Tag", isNew: false }], ariaLabel: "Tags" },
    });
    const chip = screen.getByTestId("flip-tag-chip");
    expect(chip.textContent).toBe("Old Tag");
    expect(screen.queryByTestId("flip-new-tag")).toBeNull();
  });

  it('renders an unresolved title as a "new tag" pill — separate element, not a text prefix', () => {
    render(TagFlipChips, {
      props: { items: [{ key: "+1", label: "+1", isNew: true }], ariaLabel: "Tags" },
    });
    const chip = screen.getByTestId("flip-new-tag");
    // The "new" marker is its OWN element, not concatenated into the title —
    // a title like "+1" must read as "+1", never "+ +1".
    expect(chip.textContent).toBe("+1new");
    const pill = chip.querySelector(".tag-flip-new-pill");
    expect(pill?.textContent).toBe("new");
    expect(chip.textContent?.startsWith("+ ")).toBe(false);
  });

  it("a mixed items list renders one of each, in order", () => {
    render(TagFlipChips, {
      props: {
        items: [
          { key: "tag_1", label: "Old Tag", isNew: false },
          { key: "Brand New Tag", label: "Brand New Tag", isNew: true },
        ],
        ariaLabel: "Tags",
      },
    });
    expect(screen.getByTestId("flip-tag-chip").textContent).toBe("Old Tag");
    expect(screen.getByTestId("flip-new-tag").textContent).toBe("Brand New Tagnew");
  });
});

describe("TagFlipChips — isTagFlipField / tagFlipItemsFor", () => {
  const tagField = {
    type: "entity_ref_list",
    picker_config: {
      create_missing: true,
      sources: [{ kind: "tag", expr: { type: "tag:tag" } }],
    },
  } as unknown as MetadataFieldDefinition;
  const refField = {
    type: "entity_ref_list",
    picker_config: { sources: [{ kind: "lore" }] },
  } as unknown as MetadataFieldDefinition;
  const schema = {
    entry_types: { "tag:tag": { name: "Tag", kind: "tag" } },
    fields: {},
  } as unknown as MetadataSchema;

  it("recognises a create_missing tag-vocabulary field, excludes a plain ref list", () => {
    expect(isTagFlipField(tagField, schema)).toBe(true);
    expect(isTagFlipField(refField, schema)).toBe(false);
    expect(isTagFlipField(undefined, schema)).toBe(false);
  });

  it("tags each item by roster membership — known id vs unresolved title", () => {
    const titleById = new Map([["tag_1", "Old Tag"]]);
    const items = tagFlipItemsFor(["tag_1", "Brand New Tag"], titleById);
    expect(items).toEqual([
      { key: "tag_1", label: "Old Tag", isNew: false },
      { key: "Brand New Tag", label: "Brand New Tag", isNew: true },
    ]);
  });

  it("a non-array value yields no items", () => {
    expect(tagFlipItemsFor("not-an-array" as never, new Map())).toEqual([]);
  });
});
