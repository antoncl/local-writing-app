// @vitest-environment happy-dom
// #1904 — the Details rail head reads as one fact: the entry's type, as
// `[glyph] Name ▾`. Opening it lists every type this document kind offers,
// with "Edit type…" trailing under a divider. No separate label, no bare
// <select>, no standalone button any more — one ColoredSelect in its quiet
// face owns the whole head. documentKind "lore" avoids the assistant
// ProviderTierPicker, which would fetch /api/ai/providers on mount (the
// #973 network guard).
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", icon: "book", fields: [] },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base", icon: "user", fields: [] },
    "lore:note": { name: "Note", kind: "lore", parent: "lore:base", fields: [] },
  },
  fields: {},
} as unknown as MetadataSchema;

const DOCUMENT_ENTRY_TYPES = [
  ["lore:base", SCHEMA.entry_types["lore:base"]],
  ["lore:character", SCHEMA.entry_types["lore:character"]],
  ["lore:note", SCHEMA.entry_types["lore:note"]],
] as never;

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
});

function mount(props: {
  entryType: string;
  readOnly?: boolean;
  onEntryTypeChange?: (entryType: string) => void;
  onCustomData?: () => void;
}) {
  render(MetadataPanel, {
    props: {
      entryType: props.entryType,
      status: "",
      metadata: {},
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: DOCUMENT_ENTRY_TYPES,
      metadataFieldIds: [],
      ...(props.readOnly !== undefined ? { readOnly: props.readOnly } : {}),
      ...(props.onEntryTypeChange ? { onEntryTypeChange: props.onEntryTypeChange } : {}),
      ...(props.onCustomData ? { onCustomData: props.onCustomData } : {}),
    },
  });
}

describe("MetadataPanel — the rail head is one control (#1904)", () => {
  it("the head is one control: glyph + type name + caret, no select, no button at rest", () => {
    mount({ entryType: "lore:character" });
    const triggers = document.querySelectorAll(".rail-type .colored-select-trigger");
    expect(triggers).toHaveLength(1);
    expect(triggers[0].textContent).toContain("Character");
    expect(triggers[0].querySelector(".colored-select-icon.ti-user")).not.toBeNull();
    expect(triggers[0].getAttribute("aria-label")).toBe("Entry type");
    expect(document.querySelector(".rail-type select")).toBeNull();
    expect(screen.queryByText("Edit type…")).toBeNull();
  });

  it("opening the head lists every type and Edit type… trails them", async () => {
    mount({ entryType: "lore:character" });
    const trigger = document.querySelector(".rail-type .colored-select-trigger") as HTMLElement;
    await fireEvent.click(trigger);

    const options = document.querySelectorAll('[role="option"]');
    expect(Array.from(options).map((o) => o.textContent?.trim())).toEqual(["Lore", "Character", "Note"]);

    const footerButton = screen.getByText("Edit type…");
    expect(footerButton).toBeTruthy();
    const lastOption = options[options.length - 1];
    expect(
      lastOption.compareDocumentPosition(footerButton) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("picking a type reports it and closes", async () => {
    const onEntryTypeChange = vi.fn();
    mount({ entryType: "lore:character", onEntryTypeChange });
    const trigger = document.querySelector(".rail-type .colored-select-trigger") as HTMLElement;
    await fireEvent.click(trigger);

    await fireEvent.click(screen.getByText("Note"));
    expect(onEntryTypeChange).toHaveBeenCalledTimes(1);
    expect(onEntryTypeChange).toHaveBeenCalledWith("lore:note");
    expect(document.querySelector(".colored-select-popover")).toBeNull();
  });

  it("Edit type… jumps and closes", async () => {
    const onCustomData = vi.fn();
    const onEntryTypeChange = vi.fn();
    mount({ entryType: "lore:character", onCustomData, onEntryTypeChange });
    const trigger = document.querySelector(".rail-type .colored-select-trigger") as HTMLElement;
    await fireEvent.click(trigger);

    await fireEvent.click(screen.getByText("Edit type…"));
    expect(onCustomData).toHaveBeenCalledTimes(1);
    expect(document.querySelector(".colored-select-popover")).toBeNull();
    expect(onEntryTypeChange).not.toHaveBeenCalled();
  });

  it("readOnly locks the pick but keeps the jump", async () => {
    const onEntryTypeChange = vi.fn();
    const onCustomData = vi.fn();
    mount({ entryType: "lore:character", readOnly: true, onEntryTypeChange, onCustomData });
    const trigger = document.querySelector(".rail-type .colored-select-trigger") as HTMLButtonElement;
    expect(trigger.disabled).toBe(false);

    await fireEvent.click(trigger);
    await fireEvent.click(screen.getByText("Note"));
    expect(onEntryTypeChange).not.toHaveBeenCalled();

    await fireEvent.click(screen.getByText("Edit type…"));
    expect(onCustomData).toHaveBeenCalledTimes(1);
  });

  it("an unresolved stored type is the head's label and a row", async () => {
    mount({ entryType: "assistant" });
    const trigger = document.querySelector(".rail-type .colored-select-trigger") as HTMLElement;
    expect(trigger.textContent).toContain("assistant");

    await fireEvent.click(trigger);
    const options = document.querySelectorAll('[role="option"]');
    expect(options[0].textContent?.trim()).toBe("assistant");

    expect(document.querySelector(".rail-type-warning")).not.toBeNull();
  });
});
