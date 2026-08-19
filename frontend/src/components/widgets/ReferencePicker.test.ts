// @vitest-environment happy-dom
// ReferencePicker had no test. The #49 runes port turns its `change` / `navigate`
// CustomEvents into `onChange` / `onNavigate` callback props. These lock both:
// a row click reports the navigation target, and removing a ref reports the
// reduced id list. Refs resolve from the in-memory loreEntries prop; a null
// schema is fine (the type pill falls back to the raw entry_type).
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
