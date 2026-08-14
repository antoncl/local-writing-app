// @vitest-environment happy-dom
// The Mutations pane's "+ New set" was a silent no-op: the button lives in the
// pane handle bar (App's mutationsActions snippet) and reached the pane body
// through a `bind:this` component ref that never populated across the
// handle → panelRegistry → RegionBody boundary. The fix routes the trigger
// through `mutationSetEditorStore`, a cross-tree store.
//
// ADR-0055 §3 then HOISTED the editor dialog itself to App root (so it opens
// from a lore card too), leaving this pane a pure browse/list surface. So the
// guard here is now two facts: the pane renders its roster (a display pane must
// have a mount test that asserts rows render — #642/#724), and the store-driven
// "+" contract still holds (opening the store is what the "+" does; a preset
// pins a new set).
import { afterEach, describe, expect, it } from "vitest";
import { get } from "svelte/store";
import { render, screen } from "@/lib/test/component";
import Mutations from "./Mutations.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import {
  mutationSetEditorStore,
  mutationSetEntriesStore,
  openNewMutationSet,
  closeMutationSetEditor,
} from "@/lib/stores/mutationSets";
import type { MetadataSchema, MutationSetEntrySummary } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: [] } },
  fields: {},
} as unknown as MetadataSchema;

function summary(over: Partial<MutationSetEntrySummary> = {}): MutationSetEntrySummary {
  return {
    id: "mutation_set_1",
    title: "Full Moon",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity: "",
    row_count: 2,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

afterEach(() => {
  closeMutationSetEditor();
  metadataSchemaStore.set(null);
  mutationSetEntriesStore.set([]);
});

describe("Mutations pane", () => {
  it("renders the mutation-set roster (a display pane's mount test)", () => {
    metadataSchemaStore.set(SCHEMA);
    mutationSetEntriesStore.set([summary({ title: "Full Moon" })]);
    render(Mutations);
    expect(screen.getByText("Full Moon")).toBeInTheDocument();
  });

  it("the '+' contract: openNewMutationSet sets the editor store, with an optional pin preset", () => {
    // The dialog mounts at App root now; the pane just triggers the store.
    openNewMutationSet(); // what the pane-handle "+" calls
    expect(get(mutationSetEditorStore)).toEqual({ editing: null });

    openNewMutationSet({ target_entity: "mira", target_entry_type: "lore:character" });
    expect(get(mutationSetEditorStore)).toEqual({
      editing: null,
      preset: { target_entity: "mira", target_entry_type: "lore:character" },
    });
  });
});
