// @vitest-environment happy-dom
// ReferencePicker had no test. The #49 runes port turns its `change` / `navigate`
// CustomEvents into `onChange` / `onNavigate` callback props. These lock both:
// a row click reports the navigation target, and removing a ref reports the
// reduced id list. Refs resolve from the in-memory loreEntries prop; a null
// schema is fine (the type pill falls back to the raw entry_type).
//
// The `embedded` block covers #1216: in the metadata rail the field row already
// prints the label, so the embedded picker must drop its own titled header
// (which doubled the label) while keeping the expand/collapse control.
import { afterEach, describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import ReferencePicker from "./ReferencePicker.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { LoreEntrySummary, MetadataFieldDefinition } from "@/lib/types";

const field = {
  name: "Characters",
  type: "entity_ref_list",
  options: [],
  picker_config: { sources: [{ kind: "lore" }] },
} as unknown as MetadataFieldDefinition;

const loreEntries = [
  { id: "lore_1", title: "Mira", entry_type: "lore:character" },
  { id: "lore_2", title: "Jonas", entry_type: "lore:character" },
] as unknown as LoreEntrySummary[];

afterEach(() => metadataSchemaStore.set(null));

describe("ReferencePicker — callback props (runes port of change/navigate)", () => {
  it("reports the navigation target through onNavigate on a row click", async () => {
    const onNavigate = vi.fn();
    render(ReferencePicker, {
      props: { field, value: ["lore_1"], ariaLabel: "Characters", loreEntries, onNavigate },
    });
    // Collapsed by default — expand the group, then click the resolved row.
    await fireEvent.click(screen.getByText("Characters"));
    await fireEvent.click(screen.getByText("Mira"));
    expect(onNavigate).toHaveBeenCalledWith({ id: "lore_1", kind: "lore" });
  });

  it("removing a ref reports the reduced id list through onChange", async () => {
    const onChange = vi.fn();
    render(ReferencePicker, {
      props: { field, value: ["lore_1", "lore_2"], ariaLabel: "Characters", loreEntries, onChange },
    });
    await fireEvent.click(screen.getByText("Characters"));
    await fireEvent.click(screen.getByLabelText("Remove Mira"));
    // entity_ref_list → the list shape is preserved; only Mira drops out.
    expect(onChange).toHaveBeenCalledWith(["lore_2"]);
  });
});

describe("ReferencePicker — embedded header (#1216)", () => {
  it("standalone: renders its own titled header carrying the field label", () => {
    render(ReferencePicker, {
      props: { field, value: [], ariaLabel: "Characters", readOnly: true },
    });
    // Correct when the picker stands alone (chat diff, draft card): the title is
    // the only label the value has.
    expect(screen.getByText("Characters")).toBeInTheDocument();
  });

  it("embedded: drops the duplicate label but keeps expand/collapse", async () => {
    render(ReferencePicker, {
      props: { field, value: [], ariaLabel: "Characters", readOnly: true, embedded: true },
    });
    // The rail already shows the label, so the picker must NOT repeat it as text.
    expect(screen.queryByText("Characters")).not.toBeInTheDocument();

    // The collapse control survives — its accessible name still names the field.
    const toggle = screen.getByRole("button", { name: /characters/i });
    // Collapsed by default; expanding reveals the (empty) reference list.
    expect(screen.queryByText("No references.")).not.toBeInTheDocument();
    await fireEvent.click(toggle);
    expect(screen.getByText("No references.")).toBeInTheDocument();
  });
});
