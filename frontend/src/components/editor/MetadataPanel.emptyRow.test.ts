// @vitest-environment happy-dom
// #1884 slice 3 — an empty row recedes: `.field-row.empty` when the field
// carries no value. `color` always shows an effective (placeholder) swatch,
// so it never reads empty.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: ["status", "alias", "nick", "tone", "mood", "hue", "kin"] } },
  fields: {
    // `status` is stored OFF metadata (NodeEditor shell state) and reaches the
    // rail as its own prop — the row must read that prop, not the metadata bag.
    status: {
      name: "Status",
      type: "select",
      options: [{ value: "draft", label: "Draft" }, { value: "complete", label: "Complete" }],
    },
    alias: { name: "Alias", type: "text" },
    // A TEXT default is only seeded into new entries — an absent value shows
    // nothing, so the row IS empty (the default rule is select-only).
    nick: { name: "Nick", type: "text", default: "n/a" },
    // A select with a declared default shows the default when unset (#1421) —
    // a value is on screen, so the row is never empty.
    mood: {
      name: "Mood",
      type: "select",
      default: "warm",
      options: [{ value: "warm", label: "Warm" }, { value: "cool", label: "Cool" }],
    },
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

function mount(metadata: EntryMetadata, status = "") {
  render(MetadataPanel, {
    props: {
      entryType: "lore:character",
      status,
      metadata,
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:character", SCHEMA.entry_types["lore:character"]]] as never,
      metadataFieldIds: ["status", "alias", "nick", "tone", "mood", "hue", "kin"],
      onMetadataChange: vi.fn(),
    },
  });
}

function rowFor(label: string): HTMLElement {
  const row = screen.getByText(label).closest(".field-row");
  if (!row) throw new Error(`no .field-row ancestor for "${label}"`);
  return row as HTMLElement;
}

// #2006: empty fields fold behind one summary line by default — open it
// before asserting on a row that may be empty.
async function openFold(): Promise<void> {
  const toggle = screen.queryByTestId("rail-fold-toggle");
  if (toggle) await fireEvent.click(toggle);
}

describe("MetadataPanel — empty rows recede (#1884 slice 3)", () => {
  it("the status row reads the `status` prop, not the metadata bag: set → not empty, blank → empty", () => {
    mount({}, "complete");
    expect(rowFor("Status").classList.contains("empty")).toBe(false);
  });

  it("a blank status is empty", async () => {
    mount({}, "");
    await openFold(); // #2006: an empty status now folds by default — open it first.
    expect(rowFor("Status").classList.contains("empty")).toBe(true);
  });

  it("a select with a declared default is never empty — the default is on screen", () => {
    mount({});
    expect(rowFor("Mood").classList.contains("empty")).toBe(false);
  });

  it("a TEXT field with a declared default is still empty when unset — nothing renders the default", async () => {
    mount({});
    await openFold(); // #2006: Nick is empty, so it folds by default — open it first.
    expect(rowFor("Nick").classList.contains("empty")).toBe(true);
  });

  it("empty metadata: alias, tone, kin are .empty; hue is not (always an effective swatch)", async () => {
    mount({});
    await openFold(); // #2006: alias/tone/kin are empty, so they fold by default — open it first.
    expect(rowFor("Alias").classList.contains("empty")).toBe(true);
    expect(rowFor("Tone").classList.contains("empty")).toBe(true);
    expect(rowFor("Kin").classList.contains("empty")).toBe(true);
    expect(rowFor("Hue").classList.contains("empty")).toBe(false);
  });

  it("a set value loses .empty; an unset sibling keeps it", async () => {
    mount({ alias: "The Painted", kin: ["lore_1"] });
    await openFold(); // #2006: Tone is still empty, so it folds by default — open it first.
    expect(rowFor("Alias").classList.contains("empty")).toBe(false);
    expect(rowFor("Kin").classList.contains("empty")).toBe(false);
    expect(rowFor("Tone").classList.contains("empty")).toBe(true);
  });
});
