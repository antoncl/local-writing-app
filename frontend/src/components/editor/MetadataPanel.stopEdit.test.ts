// @vitest-environment happy-dom
// ADR-0095 §8 (decisions 2/5/6) — at a scrub stop, a field a mutation can
// target writes via `onStopFieldEdit` instead of `onMetadataChange`/
// `onStatusChange`; a computed field stays locked; a text field's edit
// control opens on the set's own row value, not the effective display.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: ["status", "eye_color", "bio", "cost"] },
  },
  fields: {
    eye_color: { name: "Eye colour", type: "text" },
    bio: { name: "Bio", type: "long_text" },
    cost: { name: "Cost", type: "computed", options: [], computed: { fn: "cost" } },
    status: {
      name: "Status",
      type: "select",
      options: [
        { value: "draft", label: "Draft" },
        { value: "complete", label: "Complete" },
      ],
    },
  },
} as unknown as MetadataSchema;

beforeEach(() => metadataSchemaStore.set(SCHEMA));

function mount(metadata: EntryMetadata, extra: Record<string, unknown> = {}) {
  const onMetadataChange = vi.fn();
  const onStatusChange = vi.fn();
  const onStopFieldEdit = vi.fn();
  const { container } = render(MetadataPanel, {
    props: {
      entryType: "lore:character",
      status: "draft",
      metadata,
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:character", SCHEMA.entry_types["lore:character"]]] as never,
      metadataFieldIds: ["status", "eye_color", "bio", "cost"],
      onMetadataChange,
      onStatusChange,
      onStopFieldEdit,
      computedFieldString: () => "42",
      ...extra,
    },
  });
  return { container, onMetadataChange, onStatusChange, onStopFieldEdit };
}

function rowFor(label: string): HTMLElement {
  const row = screen.getByText(label).closest(".field-row");
  if (!row) throw new Error(`no .field-row ancestor for "${label}"`);
  return row as HTMLElement;
}

describe("MetadataPanel — stop editing (ADR-0095 §8)", () => {
  it("an editable scalar row writes via onStopFieldEdit, never onMetadataChange", async () => {
    const { onMetadataChange, onStopFieldEdit } = mount({ eye_color: "brown" }, { scrubbed: true, readOnly: false });
    await fireEvent.click(screen.getByRole("button", { name: /^Edit Eye colour/ }));
    const input = rowFor("Eye colour").querySelector("input") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "silver" } });

    expect(onStopFieldEdit).toHaveBeenCalledWith("eye_color", "silver");
    expect(onMetadataChange).not.toHaveBeenCalled();
  });

  it("status routes to onStopFieldEdit at a stop too", async () => {
    const { onStatusChange, onStopFieldEdit } = mount({}, { scrubbed: true, readOnly: false });
    await fireEvent.click(screen.getByRole("button", { name: /^Edit Status/ }));
    await fireEvent.click(screen.getByRole("button", { name: "Status" }));
    await fireEvent.click(screen.getByRole("option", { name: "Complete" }));

    expect(onStopFieldEdit).toHaveBeenCalledWith("status", "complete");
    expect(onStatusChange).not.toHaveBeenCalled();
  });

  it("a computed field stays locked at a stop — no edit hit at all", () => {
    mount({}, { scrubbed: true, readOnly: false });
    // Computed rows render a static lock glyph, never a `.fr-rest-hit`.
    const row = rowFor("Cost");
    expect(row.querySelector(".fr-rest-hit")).toBeNull();
    expect(row.querySelector(".ti-lock")).not.toBeNull();
  });

  // `bio` (long_text) renders through MetadataLongTextEditor — a TipTap
  // (contenteditable) widget, not a plain `<textarea>`, so its bound value
  // can't be read back off the DOM under happy-dom. Decision 5's seed logic
  // itself (replace-row-wins, else the add-row fragment, else "") is unit-
  // tested directly on `buildRailRowModel` in `fieldRowModel.test.ts`
  // ("ADR-0095 §8 decision 5") — this only pins that a stop-editable text row
  // renders (mounts) at all, which the two assertions above already imply.
});
