// @vitest-environment happy-dom
// The Staged-changes surface (ADR-0055 §3). `pinnedSetsFor` is unit-tested
// beside it; this pins the PANEL's own contract — that the reverse-ref ∩ roster
// set actually RENDERS as rows (the #642/#724 lesson: a view-layer filter can
// silently empty a data pane), that ＋New opens the editor pinned to THIS
// entity, and that clicking a row opens that set for editing.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { get } from "svelte/store";
import { render, screen, fireEvent } from "@/lib/test/component";
import PinnedSetsPanel from "./PinnedSetsPanel.svelte";
import { referenceIndexStore } from "@/lib/stores/references";
import { mutationSetEntriesStore, mutationSetEditorStore, closeMutationSetEditor } from "@/lib/stores/mutationSets";
import { api } from "@/lib/api";
import type { MutationSetEntry, MutationSetEntrySummary } from "@/lib/types";

function set(over: Partial<MutationSetEntrySummary>): MutationSetEntrySummary {
  return {
    id: "s",
    title: "Change",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity: "",
    row_count: 1,
    rows: [],
    anchors: [],
    state: over.target_entity || "target_entity" in over ? "staged" : "template",
    pin_missing: false,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

beforeEach(() => {
  // Two sets are pinned to "mira", a third is reusable (not a referrer).
  mutationSetEntriesStore.set([
    set({ id: "wolf", title: "Becomes a werewolf", target_entity: "mira" }),
    set({ id: "scar", title: "Gains a scar", target_entity: "mira" }),
    set({ id: "reusable", title: "Any promotion", target_entity: "" }),
  ]);
  referenceIndexStore.set(new Map([["mira", new Set(["wolf", "scar"])]]));
});
afterEach(() => {
  mutationSetEntriesStore.set([]);
  referenceIndexStore.set(new Map());
  closeMutationSetEditor();
  vi.restoreAllMocks();
});

describe("PinnedSetsPanel (ADR-0055 §3)", () => {
  it("renders the sets pinned to this entity and excludes reusable ones", () => {
    render(PinnedSetsPanel, { props: { entityId: "mira", entityEntryType: "lore:character" } });
    expect(screen.getByRole("button", { name: "Becomes a werewolf" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gains a scar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Any promotion" })).toBeNull();
  });

  it("excludes an active (anchored) set from the staged/placeable list (ADR-0095 §2/§9), listing it read-only instead", () => {
    // "scar" is anchored in a scene — it drops out of the card's staged-only
    // placeable list (a Delete there would be wrong, nothing anchors it there)
    // and shows up read-only below instead (ADR-0095 S5, #2233).
    mutationSetEntriesStore.set([
      set({ id: "wolf", title: "Becomes a werewolf", target_entity: "mira" }),
      set({
        id: "scar",
        title: "Gains a scar",
        target_entity: "mira",
        state: "active",
        anchors: [{ anchor_id: "a1", scene_id: "s1", scene_title: "Ch 1" }],
      }),
    ]);
    render(PinnedSetsPanel, { props: { entityId: "mira", entityEntryType: "lore:character" } });
    expect(screen.getByRole("button", { name: "Becomes a werewolf" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Gains a scar" })).toBeNull();
    expect(screen.getByText("Gains a scar")).toBeInTheDocument();
    expect(screen.getByText("Ch 1")).toBeInTheDocument();
    // Read-only: no Delete action for an active set on the card (deleting one
    // is a pane action, with its own confirm).
    expect(screen.queryByLabelText("Delete Gains a scar")).toBeNull();
  });

  it("offers Delete on a staged set; deleting it refreshes the roster", async () => {
    const deleteSpy = vi.spyOn(api, "deleteMutationSetEntry").mockResolvedValue({
      entries: [set({ id: "reusable", title: "Any promotion", target_entity: "" })],
    });
    render(PinnedSetsPanel, { props: { entityId: "mira", entityEntryType: "lore:character" } });

    await fireEvent.click(screen.getByLabelText("Delete Becomes a werewolf"));

    expect(deleteSpy).toHaveBeenCalledWith("wolf");
    // The roster the delete call returned replaces the store — the werewolf
    // set (and its row) is gone.
    expect(screen.queryByRole("button", { name: "Becomes a werewolf" })).toBeNull();
  });

  it("shows the placing hint naming the entity, under the list", () => {
    render(PinnedSetsPanel, { props: { entityId: "mira", entityEntryType: "lore:character", entityTitle: "Mira" } });
    expect(
      screen.getByText("Place a staged set from a scene: type /mutate, pick Mira, then Apply a saved set."),
    ).toBeInTheDocument();
  });

  it("＋New opens the editor pinned to this entity + its type", async () => {
    render(PinnedSetsPanel, { props: { entityId: "mira", entityEntryType: "lore:character" } });
    await fireEvent.click(screen.getByRole("button", { name: /New/ }));
    expect(get(mutationSetEditorStore)).toEqual({
      editing: null,
      preset: { target_entity: "mira", target_entry_type: "lore:character" },
    });
  });

  it("opens a pinned set for editing on row click", async () => {
    const full = { id: "wolf", title: "Becomes a werewolf", target_entity: "mira" } as unknown as MutationSetEntry;
    const getFull = vi.spyOn(api, "getMutationSetEntry").mockResolvedValue(full);
    render(PinnedSetsPanel, { props: { entityId: "mira", entityEntryType: "lore:character" } });

    await fireEvent.click(screen.getByRole("button", { name: "Becomes a werewolf" }));
    await tick();
    expect(getFull).toHaveBeenCalledWith("wolf");
    expect(get(mutationSetEditorStore)).toEqual({ editing: full });
  });

  it("does not render when the entity type is unknown", () => {
    const { container } = render(PinnedSetsPanel, { props: { entityId: "mira", entityEntryType: "" } });
    expect(container.querySelector(".entry-pinned-sets")).toBeNull();
  });
});
