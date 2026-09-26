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
import { loreEntriesStore } from "@/lib/stores/lore";
import { confirmService } from "@/lib/stores/confirmService.svelte";
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
  anchors: [],
  state: "template",
  pin_missing: false,
  source_layer_id: "",
  source_layer_label: "",
}));
const deleteMutationSetEntry = vi.fn(async (_id: string) => ({ entries: [] as MutationSetEntrySummary[] }));
vi.mock("@/lib/api", () => ({
  api: {
    getMutationSetEntry: (...args: unknown[]) => getMutationSetEntry(...(args as [string])),
    promotionTargets: vi.fn(async () => []),
    deleteMutationSetEntry: (...args: unknown[]) => deleteMutationSetEntry(...(args as [string])),
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
    rows: [],
    anchors: [],
    state: "template",
    pin_missing: false,
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
  loreEntriesStore.set([]);
  getMutationSetEntry.mockClear();
  deleteMutationSetEntry.mockClear();
  vi.restoreAllMocks();
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

  it("hides Promote for an active set (anchored in a scene, out of ADR-0078 Scope)", () => {
    metadataSchemaStore.set(SCHEMA);
    mutationSetEntriesStore.set([summary({ title: "Full Moon", state: "active" })]);
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

describe("Mutations pane: grouped by state (ADR-0095 S5, #2233)", () => {
  it("renders three groups in order — Templates, Staged, Active — with the right members and counts", () => {
    metadataSchemaStore.set(SCHEMA);
    mutationSetEntriesStore.set([
      summary({ id: "t1", title: "Werewolf dusk", state: "template" }),
      summary({ id: "s1", title: "Becomes a werewolf", state: "staged", target_entity: "mira" }),
      summary({ id: "s2", title: "Gains a scar", state: "staged", target_entity: "mira" }),
      summary({
        id: "a1",
        title: "Loses an eye",
        state: "active",
        target_entity: "mira",
        anchors: [{ anchor_id: "anc1", scene_id: "sc1", scene_title: "Chapter 3" }],
      }),
    ]);
    const { container } = render(Mutations);

    const headings = Array.from(container.querySelectorAll(".node-row.group-header .node-row-text")).map((el) =>
      el.textContent?.trim(),
    );
    expect(headings).toEqual(["Templates", "Staged", "Active"]);

    const counts = Array.from(container.querySelectorAll(".node-row.group-header .pill")).map((el) => el.textContent);
    expect(counts).toEqual(["1", "2", "1"]);

    expect(screen.getByText("Werewolf dusk")).toBeInTheDocument();
    expect(screen.getByText("Becomes a werewolf")).toBeInTheDocument();
    expect(screen.getByText("Gains a scar")).toBeInTheDocument();
    expect(screen.getByText("Loses an eye")).toBeInTheDocument();
  });

  it("an active linked set shows its places and the 'N places' badge", () => {
    metadataSchemaStore.set(SCHEMA);
    // loreEntriesStore feeds the entity title for a staged/active row's sub-line.
    loreEntriesStore.set([{ id: "mira", title: "Mira", body: "", entry_type: "lore:character", metadata: {} }]);
    mutationSetEntriesStore.set([
      summary({
        id: "a1",
        title: "Loses an eye",
        state: "active",
        target_entity: "mira",
        anchors: [
          { anchor_id: "anc1", scene_id: "sc1", scene_title: "Chapter 3" },
          { anchor_id: "anc2", scene_id: "sc2", scene_title: "Chapter 7" },
        ],
      }),
    ]);
    render(Mutations);

    expect(screen.getByText("Mira — Chapter 3, Chapter 7")).toBeInTheDocument();
    expect(screen.getByText("2 places")).toBeInTheDocument();
    loreEntriesStore.set([]);
  });

  it("labels an untitled set via mutationSetLabel", () => {
    metadataSchemaStore.set(SCHEMA);
    mutationSetEntriesStore.set([
      summary({
        id: "u1",
        title: "",
        state: "template",
        rows: [{ id: "r1", field: "rank", op: "replace", value: "Captain" }],
      }),
    ]);
    render(Mutations);

    expect(screen.getByText("rank → Captain")).toBeInTheDocument();
  });
});

describe("Mutations pane: deleting an active set warns (ADR-0095 §9)", () => {
  it("asks for confirmation, naming the label and the scene count, before deleting an active set", async () => {
    const requestSpy = vi.spyOn(confirmService, "request").mockImplementation(() => {});
    metadataSchemaStore.set(SCHEMA);
    mutationSetEntriesStore.set([
      summary({
        title: "Full Moon",
        state: "active",
        anchors: [
          { anchor_id: "a1", scene_id: "scene_1", scene_title: "Chapter One" },
          { anchor_id: "a2", scene_id: "scene_2", scene_title: "Chapter Two" },
        ],
      }),
    ]);
    render(Mutations);

    await fireEvent.click(screen.getByLabelText("Delete Full Moon"));

    expect(deleteMutationSetEntry).not.toHaveBeenCalled();
    expect(requestSpy).toHaveBeenCalledTimes(1);
    const request = requestSpy.mock.calls[0][0];
    expect(request.message).toContain("Full Moon");
    expect(request.message).toContain("2 scene(s)");

    await request.onConfirm();
    expect(deleteMutationSetEntry).toHaveBeenCalledWith("mutation_set_1");
  });

  it("deletes a staged set without asking", async () => {
    const requestSpy = vi.spyOn(confirmService, "request").mockImplementation(() => {});
    metadataSchemaStore.set(SCHEMA);
    mutationSetEntriesStore.set([summary({ title: "Full Moon", state: "staged" })]);
    render(Mutations);

    await fireEvent.click(screen.getByLabelText("Delete Full Moon"));

    expect(requestSpy).not.toHaveBeenCalled();
    expect(deleteMutationSetEntry).toHaveBeenCalledWith("mutation_set_1");
  });

  it("deletes a template without asking", async () => {
    const requestSpy = vi.spyOn(confirmService, "request").mockImplementation(() => {});
    metadataSchemaStore.set(SCHEMA);
    mutationSetEntriesStore.set([summary({ title: "Full Moon", state: "template" })]);
    render(Mutations);

    await fireEvent.click(screen.getByLabelText("Delete Full Moon"));

    expect(requestSpy).not.toHaveBeenCalled();
    expect(deleteMutationSetEntry).toHaveBeenCalledWith("mutation_set_1");
  });
});
