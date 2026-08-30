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
import { afterEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { render, screen, fireEvent } from "@/lib/test/component";
import Mutations from "./Mutations.svelte";
import { metadataSchemaStore, metadataSchemaLayersStore } from "@/lib/stores/schema";
import {
  mutationSetEditorStore,
  mutationSetEntriesStore,
  openNewMutationSet,
  closeMutationSetEditor,
} from "@/lib/stores/mutationSets";
import type { MetadataSchema, MetadataSchemaLayer, MutationSetEntry, MutationSetEntrySummary } from "@/lib/types";

// The Promote row action (ADR-0078 §2/§9 slice 4) opens PromoteModal, which
// fetches its own roster on open — stub the api so the test never reaches a
// real backend (#973 network guard). `getMutationSetEntry` echoes the summary
// back as a "full" entry (this pane only needs id/title to open the modal).
const getMutationSetEntry = vi.fn(async (id: string): Promise<MutationSetEntry> => ({
  id,
  title: "Full Moon",
  revision: "1",
  entry_type: "mutation_set:mutation_set",
  target_entry_type: "lore:character",
  target_entity: "",
  rows: [],
  placed: false,
  source_layer_id: "",
  source_layer_label: "",
}));
vi.mock("@/lib/api", () => ({
  api: {
    getMutationSetEntry: (...args: unknown[]) => getMutationSetEntry(...(args as [string])),
    promotionTargets: vi.fn(async () => []),
  },
}));

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
    placed: false,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

afterEach(() => {
  closeMutationSetEditor();
  metadataSchemaStore.set(null);
  mutationSetEntriesStore.set([]);
  metadataSchemaLayersStore.set([]);
  getMutationSetEntry.mockClear();
});

describe("Mutations pane", () => {
  it("renders the mutation-set roster (a display pane's mount test)", () => {
    metadataSchemaStore.set(SCHEMA);
    mutationSetEntriesStore.set([summary({ title: "Full Moon", row_count: 2 })]);
    render(Mutations);
    // Assert real data-derived output, not just that the pane mounted (#724):
    // the title, the target-type detail resolved through the schema (typeLabel),
    // the row_count pill, and the per-row delete affordance keyed by title.
    expect(screen.getByText("Full Moon")).toBeInTheDocument();
    expect(screen.getByText("for Character")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByLabelText("Delete Full Moon")).toBeInTheDocument();
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

  it("offers Promote for an owned, staged set, and opens PromoteModal with the fetched entry on click", async () => {
    metadataSchemaStore.set(SCHEMA);
    mutationSetEntriesStore.set([summary({ id: "mset-1", title: "Full Moon" })]);
    render(Mutations);

    const promoteButton = screen.getByRole("button", { name: "Promote Full Moon" });
    await fireEvent.click(promoteButton);

    expect(getMutationSetEntry).toHaveBeenCalledWith("mset-1");
    // PromoteModal is now open on the fetched entry — its own dialogue chrome
    // renders (the actual plan/bucket rendering is PromoteModal's own test).
    // The row's own "Promote to…" button also reads that text, so key on the
    // modal's dialog role instead of the ambiguous string.
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("No ancestor projects to promote into.")).toBeInTheDocument();
  });

  it("hides Promote for a placed one-off (anchored in a scene, out of ADR-0078 Scope)", () => {
    metadataSchemaStore.set(SCHEMA);
    mutationSetEntriesStore.set([summary({ title: "Full Moon", placed: true })]);
    render(Mutations);

    expect(screen.queryByRole("button", { name: "Promote Full Moon" })).toBeNull();
  });

  it("hides Promote for a set inherited from an ancestor project", () => {
    metadataSchemaStore.set(SCHEMA);
    metadataSchemaLayersStore.set([
      { id: "root", label: "World", folder_path: "", schema_path: "", exists: true },
      { id: "book", label: "Book", folder_path: "", schema_path: "", exists: true },
    ] satisfies MetadataSchemaLayer[]);
    mutationSetEntriesStore.set([summary({ title: "Full Moon", source_layer_id: "root" })]);
    render(Mutations);

    expect(screen.queryByRole("button", { name: "Promote Full Moon" })).toBeNull();
  });
});
