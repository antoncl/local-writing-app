// @vitest-environment happy-dom
// The mutation-set editor gained a PINNED mode (ADR-0055 §3): opened with a
// `preset` from a lore card (or editing a set that already carries
// `target_entity`), it locks the type to that entity's, shows "Pinned to …"
// instead of the type picker, and threads the pin through save. A reusable set
// (no preset, no pin) is unchanged: a type picker and no entity.
import { afterEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import MutationSetEditor from "./MutationSetEditor.svelte";
import { api } from "@/lib/api";
import type { LoreEntrySummary, MetadataSchema, MutationSetEntry } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: [] } },
  fields: {},
} as unknown as MetadataSchema;

const MIRA = { id: "mira", title: "Mira", entry_type: "lore:character", metadata: {} } as unknown as LoreEntrySummary;

const NOOP = () => {};

afterEach(() => vi.restoreAllMocks());

describe("MutationSetEditor pinned mode (ADR-0055 §3)", () => {
  it("reusable mode (no preset) shows the type picker, no pin", () => {
    const { container } = render(MutationSetEditor, {
      props: { schema: SCHEMA, onSaved: NOOP, onCancel: NOOP },
    });
    expect(screen.getByText("New mutation set")).toBeInTheDocument();
    // "Applies to" is the type-picker label; it is present only in reusable mode.
    expect(screen.getByText("Applies to")).toBeInTheDocument();
    expect(container.querySelector(".tset-pin")).toBeNull();
  });

  it("pinned mode (preset) locks to the entity: no type picker, a 'Pinned to' line", () => {
    render(MutationSetEditor, {
      props: {
        schema: SCHEMA,
        loreEntries: [MIRA],
        preset: { target_entity: "mira", target_entry_type: "lore:character" },
        onSaved: NOOP,
        onCancel: NOOP,
      },
    });
    // Title no longer relabels by pin (#1640) — both modes read "New mutation
    // set"; pinned mode is distinguished by the "Pinned to" line, not the title.
    expect(screen.getByText("New mutation set")).toBeInTheDocument();
    // The type picker is gone (its "Applies to" label absent); the pin is shown.
    expect(screen.queryByText("Applies to")).toBeNull();
    expect(screen.getByText(/Mira · Character/)).toBeInTheDocument();
  });

  it("threads the pin through save (editing a pinned set)", async () => {
    const saveSpy = vi.spyOn(api, "saveMutationSetEntry").mockResolvedValue({} as MutationSetEntry);
    const initial = {
      id: "set_1",
      title: "Becomes a werewolf",
      revision: "r1",
      entry_type: "mutation_set:mutation_set",
      target_entry_type: "lore:character",
      target_entity: "mira",
      rows: [{ field: "title", op: "replace", value: "The Wolf" }],
      source_layer_id: "",
      source_layer_label: "",
    } as MutationSetEntry;
    render(MutationSetEditor, {
      props: { schema: SCHEMA, loreEntries: [MIRA], initial, onSaved: NOOP, onCancel: NOOP },
    });
    // Editing a set that already carries a pin renders pinned mode (no type
    // picker, a 'Pinned to' line) — not only the preset-driven open path.
    expect(screen.queryByText("Applies to")).toBeNull();
    expect(screen.getByText(/Mira · Character/)).toBeInTheDocument();
    // Edit mode seeds the row, so Save is enabled with no further input.
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await tick();
    expect(saveSpy).toHaveBeenCalledWith(expect.objectContaining({ target_entity: "mira" }));
  });
});
