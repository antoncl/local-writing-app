// @vitest-environment happy-dom
// The Mutations pane's "+ New set" was a silent no-op: the button lives in the
// pane handle bar (App's mutationsActions snippet) and reached the pane body
// through a `bind:this` component ref that never populated across the
// handle → panelRegistry → RegionBody boundary — so `mutationsPane?.openNew()`
// short-circuited. The fix routes the trigger through `mutationSetEditorStore`.
// This pins that contract: setting the store opens the editor IN the pane, so
// the "+" (which sets the store) can never be a no-op again.
import { afterEach, describe, expect, it } from "vitest";
import { tick } from "svelte";
import { render, screen } from "@/lib/test/component";
import Mutations from "./Mutations.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import {
  mutationSetEditorStore,
  mutationSetEntriesStore,
  openNewMutationSet,
  closeMutationSetEditor,
} from "@/lib/stores/mutationSets";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: [] } },
  fields: {},
} as unknown as MetadataSchema;

afterEach(() => {
  closeMutationSetEditor();
  metadataSchemaStore.set(null);
  mutationSetEntriesStore.set([]);
});

describe("Mutations pane — New-set opens via the store, not a cross-tree ref", () => {
  it("mounts the editor when the editor store is opened (the '+' contract)", async () => {
    metadataSchemaStore.set(SCHEMA);
    render(Mutations, { props: { loreEntries: [] } });

    // Closed at rest — the empty-state copy shows, the dialog does not.
    expect(screen.queryByText("New mutation set")).not.toBeInTheDocument();

    openNewMutationSet(); // what the pane-handle "+" calls
    await tick();

    expect(screen.getByText("New mutation set")).toBeInTheDocument();
    expect(mutationSetEditorStore).toBeTruthy();
  });

  it("closing the store tears the editor back down", async () => {
    metadataSchemaStore.set(SCHEMA);
    render(Mutations, { props: { loreEntries: [] } });
    openNewMutationSet();
    await tick();
    expect(screen.getByText("New mutation set")).toBeInTheDocument();

    closeMutationSetEditor();
    await tick();
    expect(screen.queryByText("New mutation set")).not.toBeInTheDocument();
  });
});
