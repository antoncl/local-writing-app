// @vitest-environment happy-dom
// #1884 slice 2 — a non-empty `entity_ref_list` row's disclosure gutter carries
// a caret that toggles the field's persisted fold state through
// `railSectionCollapse` (`field:<fieldId>`, global like the rail's other
// sections); an empty list or a single `entity_ref` never gets the caret — the
// gutter stays the plain `.fr-disc` span every other field row uses.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { railSectionCollapse } from "@/lib/stores/railSectionCollapse.svelte";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: ["allies", "home"] } },
  fields: {
    allies: {
      name: "Allies",
      type: "entity_ref_list",
      options: [],
      picker_config: { sources: [{ kind: "lore" }] },
    },
    home: {
      name: "Home Place",
      type: "entity_ref",
      options: [],
      picker_config: { sources: [{ kind: "lore" }] },
    },
  },
} as unknown as MetadataSchema;

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
  // Reset the (global) singleton store between tests — it is not remounted per
  // test the way the component under test is.
  localStorage.clear();
  railSectionCollapse.set("field:allies", false);
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
      metadataFieldIds: ["allies", "home"],
      onMetadataChange: vi.fn(),
    },
  });
}

function rowFor(label: string): HTMLElement {
  const row = screen.getByText(label).closest(".field-row");
  if (!row) throw new Error(`no .field-row ancestor for "${label}"`);
  return row as HTMLElement;
}

describe("MetadataPanel — folding list gutter caret (#1884 slice 2)", () => {
  it("a non-empty entity_ref_list row has a gutter toggle, collapsed by default", () => {
    mount({ allies: ["lore_1"] });
    const toggle = rowFor("Allies").querySelector(".fr-disc-toggle");
    expect(toggle).not.toBeNull();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("clicking the gutter toggle flips aria-expanded and the persisted store", async () => {
    mount({ allies: ["lore_1"] });
    const toggle = rowFor("Allies").querySelector(".fr-disc-toggle") as HTMLElement;
    await fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(railSectionCollapse.isExpanded("field:allies", false)).toBe(true);
  });

  it("the caret's state reaches the picker: with a stubbed layout the +N chip goes away on click (expanded threaded through FieldValueEditor)", async () => {
    // Same stub as ReferencePicker.test.ts: a 200px row, pills 0/1 on the
    // first line, pill 2 wrapped — folded shows 2 + `+1`; expanded shows 3.
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const zero = { left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON() {} };
      if (this.classList.contains("ref-pill-row")) return { ...zero, right: 200, width: 200, bottom: 24, height: 24 };
      if (this.classList.contains("ref-pill") && !this.classList.contains("ref-pill-more")) {
        const idx = [...document.querySelectorAll(".ref-pill:not(.ref-pill-more)")].indexOf(this);
        const def = [{ top: 0, right: 60 }, { top: 0, right: 120 }, { top: 24, right: 180 }][idx] ?? { top: 0, right: 0 };
        return { ...zero, top: def.top, right: def.right, width: def.right, bottom: def.top + 24, height: 24 };
      }
      return zero;
    });
    try {
      mount({ allies: ["lore_1", "lore_2", "lore_3"] });
      const row = rowFor("Allies");
      expect(row.querySelectorAll(".ref-pill-slot.overflow")).toHaveLength(1);
      expect(row.querySelector(".ref-pill-more")?.textContent).toBe("+1");
      await fireEvent.click(row.querySelector(".fr-disc-toggle") as HTMLElement);
      expect(row.querySelectorAll(".ref-pill-slot.overflow")).toHaveLength(0);
      expect(row.querySelector(".ref-pill-more")).toBeNull();
      // And the chip itself flips the same persisted state.
      await fireEvent.click(row.querySelector(".fr-disc-toggle") as HTMLElement);
      expect(row.querySelector(".ref-pill-more")?.textContent).toBe("+1");
      await fireEvent.click(row.querySelector(".ref-pill-more") as HTMLElement);
      expect(row.querySelector(".ref-pill-more")).toBeNull();
      expect(railSectionCollapse.isExpanded("field:allies", false)).toBe(true);
    } finally {
      vi.restoreAllMocks();
    }
  });

  it("an empty entity_ref_list row has no gutter button — a plain span", () => {
    mount({ allies: [] });
    const gutter = rowFor("Allies").querySelector(".fr-disc") as HTMLElement;
    expect(gutter.tagName).toBe("SPAN");
    expect(gutter.classList.contains("fr-disc-toggle")).toBe(false);
  });

  it("a single entity_ref row has no gutter button — a plain span", () => {
    mount({ allies: [], home: "lore_2" });
    const gutter = rowFor("Home Place").querySelector(".fr-disc") as HTMLElement;
    expect(gutter.tagName).toBe("SPAN");
    expect(gutter.classList.contains("fr-disc-toggle")).toBe(false);
  });
});
