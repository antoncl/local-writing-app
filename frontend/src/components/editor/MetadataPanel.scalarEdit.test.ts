// @vitest-environment happy-dom
// #1884 slice 4 — scalars read at rest, edit on click: a scalar row (text,
// select, boolean, plus the dedicated `status` row) shows its value through
// the canonical read-only display until the writer opens it; only one row is
// open at a time.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": {
      name: "Character",
      kind: "lore",
      fields: ["status", "alias", "tone", "flag", "notes", "kin"],
    },
  },
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
    flag: { name: "Flag", type: "boolean" },
    status: {
      name: "Status",
      type: "select",
      options: [
        { value: "draft", label: "Draft" },
        { value: "complete", label: "Complete" },
      ],
    },
    notes: { name: "Notes", type: "long_text" },
    kin: {
      name: "Kin",
      type: "entity_ref_list",
      options: [],
      picker_config: { sources: [{ kind: "lore" }] },
    },
  },
} as unknown as MetadataSchema;

beforeEach(() => metadataSchemaStore.set(SCHEMA));

function mount(metadata: EntryMetadata, status = "", extra: Record<string, unknown> = {}) {
  const onMetadataChange = vi.fn();
  const onStatusChange = vi.fn();
  const { container } = render(MetadataPanel, {
    props: {
      entryType: "lore:character",
      status,
      metadata,
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:character", SCHEMA.entry_types["lore:character"]]] as never,
      metadataFieldIds: ["status", "alias", "tone", "flag", "notes", "kin"],
      onMetadataChange,
      onStatusChange,
      ...extra,
    },
  });
  return { container, onMetadataChange, onStatusChange };
}

function rowFor(label: string): HTMLElement {
  const row = screen.getByText(label).closest(".field-row");
  if (!row) throw new Error(`no .field-row ancestor for "${label}"`);
  return row as HTMLElement;
}

describe("MetadataPanel — scalars read at rest, edit on click (#1884 slice 4)", () => {
  it("rest: shows the text value, no input, plus an Edit hit; long_text/entity_ref_list rows have no hit", () => {
    mount({ alias: "The Painted" });
    const row = rowFor("Alias");
    expect(row.querySelector("input")).toBeNull();
    expect(row.querySelector(".fr-rest-value")?.textContent).toContain("The Painted");
    expect(screen.getByRole("button", { name: "Edit Alias" })).toBeTruthy();

    expect(rowFor("Notes").querySelector(".fr-rest-hit")).toBeNull();
    expect(rowFor("Kin").querySelector(".fr-rest-hit")).toBeNull();
  });

  it("empty rest: shows the + affordance and a 'Set …' title", () => {
    mount({});
    const row = rowFor("Alias");
    expect(row.querySelector(".fr-rest-add")?.textContent).toBe("+");
    const hit = row.querySelector(".fr-rest-hit") as HTMLElement;
    expect(hit.title.startsWith("Set")).toBe(true);
  });

  it("click the hit opens the row: input appears, focused, .editing set; typing writes through", async () => {
    const { onMetadataChange } = mount({ alias: "The Painted" });
    await fireEvent.click(screen.getByRole("button", { name: "Edit Alias" }));

    const row = rowFor("Alias");
    expect(row.classList.contains("editing")).toBe(true);
    const input = row.querySelector("input") as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(document.activeElement).toBe(input);

    await fireEvent.input(input, { target: { value: "X" } });
    expect(onMetadataChange).toHaveBeenCalledWith(expect.objectContaining({ alias: "X" }));
  });

  it("clicking the LABEL opens the row too (a convenience; the hit button is the keyboard path)", async () => {
    mount({ alias: "The Painted" });
    await fireEvent.click(screen.getByText("Alias"));
    const row = rowFor("Alias");
    expect(row.classList.contains("editing")).toBe(true);
    expect(row.querySelector("input")).not.toBeNull();
  });

  it("Escape returns the open row to rest", async () => {
    mount({ alias: "The Painted" });
    await fireEvent.click(screen.getByRole("button", { name: "Edit Alias" }));
    const row = rowFor("Alias");
    const input = row.querySelector("input") as HTMLInputElement;

    await fireEvent.keyDown(input, { key: "Escape" });

    expect(row.querySelector("input")).toBeNull();
    expect(row.querySelector(".fr-rest-hit")).not.toBeNull();
    expect(row.classList.contains("editing")).toBe(false);
  });

  it("one row edits at a time: opening Tone closes Alias", async () => {
    mount({ alias: "The Painted" });
    await fireEvent.click(screen.getByRole("button", { name: "Edit Alias" }));
    expect(rowFor("Alias").classList.contains("editing")).toBe(true);

    await fireEvent.click(screen.getByRole("button", { name: "Edit Tone" }));

    expect(rowFor("Alias").classList.contains("editing")).toBe(false);
    expect(rowFor("Tone").classList.contains("editing")).toBe(true);
  });

  it("single pick (select): picking an option writes through and returns Tone to rest", async () => {
    const { onMetadataChange } = mount({ tone: "warm" });
    await fireEvent.click(screen.getByRole("button", { name: "Edit Tone" }));
    expect(rowFor("Tone").classList.contains("editing")).toBe(true);

    // Open the live ColoredSelect trigger (named "Tone") and pick "Cool".
    await fireEvent.click(screen.getByRole("button", { name: "Tone" }));
    await fireEvent.click(screen.getByRole("option", { name: "Cool" }));

    expect(onMetadataChange).toHaveBeenCalledWith(expect.objectContaining({ tone: "cool" }));
    expect(rowFor("Tone").classList.contains("editing")).toBe(false);
  });

  it("status: rest shows a read-only pill; picking a new status calls onStatusChange and returns to rest", async () => {
    const { onStatusChange } = mount({}, "draft");
    const statusRow = rowFor("Status");
    expect(statusRow.querySelector(".fr-rest-hit")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Edit Status" })).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: "Edit Status" }));
    expect(statusRow.classList.contains("editing")).toBe(true);

    await fireEvent.click(screen.getByRole("button", { name: "Status" }));
    await fireEvent.click(screen.getByRole("option", { name: "Complete" }));

    expect(onStatusChange).toHaveBeenCalledWith("complete");
    expect(statusRow.classList.contains("editing")).toBe(false);
  });

  it("whole-panel readOnly: no .fr-rest-hit anywhere; Alias still shows its value read-only", () => {
    mount({ alias: "The Painted" }, "", { readOnly: true });
    expect(document.querySelector(".fr-rest-hit")).toBeNull();
    expect(screen.getByText("The Painted")).toBeTruthy();
  });

  it("focus leaving the row closes it; focus into a colored-select-popover keeps it open", async () => {
    mount({ alias: "The Painted" });
    await fireEvent.click(screen.getByRole("button", { name: "Edit Alias" }));
    const row = rowFor("Alias");
    const input = row.querySelector("input") as HTMLInputElement;

    const outside = document.createElement("button");
    document.body.appendChild(outside);
    await fireEvent.focusOut(input, { relatedTarget: outside });
    expect(row.classList.contains("editing")).toBe(false);
    outside.remove();

    // Re-open, then focus out into a body-portaled popover — stays editing.
    await fireEvent.click(screen.getByRole("button", { name: "Edit Alias" }));
    const input2 = rowFor("Alias").querySelector("input") as HTMLInputElement;
    const popover = document.createElement("div");
    popover.className = "colored-select-popover";
    const popoverChild = document.createElement("button");
    popover.appendChild(popoverChild);
    document.body.appendChild(popover);
    await fireEvent.focusOut(input2, { relatedTarget: popoverChild });
    expect(rowFor("Alias").classList.contains("editing")).toBe(true);
    popover.remove();
  });
});
