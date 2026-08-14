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
    placed: false,
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
    expect(screen.getByRole("button", { name: /Becomes a werewolf/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Gains a scar/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Any promotion/ })).toBeNull();
  });

  it("excludes a placed set from the pending list (ADR-0055 §5)", () => {
    // "scar" has been placed into a scene — it drops out of the card's pending
    // list (kept only as the chat's provenance).
    mutationSetEntriesStore.set([
      set({ id: "wolf", title: "Becomes a werewolf", target_entity: "mira" }),
      set({ id: "scar", title: "Gains a scar", target_entity: "mira", placed: true }),
    ]);
    render(PinnedSetsPanel, { props: { entityId: "mira", entityEntryType: "lore:character" } });
    expect(screen.getByRole("button", { name: /Becomes a werewolf/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Gains a scar/ })).toBeNull();
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

    await fireEvent.click(screen.getByRole("button", { name: /Becomes a werewolf/ }));
    await tick();
    expect(getFull).toHaveBeenCalledWith("wolf");
    expect(get(mutationSetEditorStore)).toEqual({ editing: full });
  });

  it("does not render when the entity type is unknown", () => {
    const { container } = render(PinnedSetsPanel, { props: { entityId: "mira", entityEntryType: "" } });
    expect(container.querySelector(".entry-pinned-sets")).toBeNull();
  });
});
