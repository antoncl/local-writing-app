// Store contract for the mutation-set roster (ADR-0095 §1/§2): a by-id lookup
// and an anchor→set lookup derived from it, `rosterLoaded`, `upsertMutationSet`
// folding a create/save/copy result in at once, and every write path bumping
// `mutationsVersion` so scrub/timeline readers refresh.
import { afterEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { mutationsVersion } from "./mutationsVersion.svelte";
import type { MutationSetEntry, MutationSetEntrySummary } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  api: { listMutationSetEntries: vi.fn() },
}));

import { api } from "@/lib/api";
import {
  clearMutationSets,
  mutationSetByAnchorIdStore,
  mutationSetEntriesStore,
  mutationSetRosterLoadedStore,
  mutationSetsByIdStore,
  refreshMutationSetEntries,
  removeMutationSetFromStore,
  setMutationSetEntries,
  upsertMutationSet,
} from "./mutationSets";

function summary(over: Partial<MutationSetEntrySummary> = {}): MutationSetEntrySummary {
  return {
    id: "s1",
    title: "Full Moon",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity: "mira",
    row_count: 1,
    rows: [],
    anchors: [],
    state: "staged",
    pin_missing: false,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

function fullEntry(over: Partial<MutationSetEntry> = {}): MutationSetEntry {
  return {
    id: "s1",
    title: "Full Moon",
    revision: "r1",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity: "mira",
    rows: [{ id: "row1", field: "mood", op: "replace", value: "numb" }],
    anchors: [],
    state: "staged",
    pin_missing: false,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

afterEach(() => {
  clearMutationSets();
  vi.restoreAllMocks();
});

describe("mutationSetsByIdStore / mutationSetByAnchorIdStore (ADR-0095 §1)", () => {
  it("indexes the roster by id and by every anchor it carries", () => {
    mutationSetEntriesStore.set([
      summary({ id: "s1", anchors: [{ anchor_id: "a1", scene_id: "sc1", scene_title: "Ch 1" }] }),
      summary({ id: "s2", anchors: [{ anchor_id: "a2", scene_id: "sc1", scene_title: "Ch 1" }, { anchor_id: "a3", scene_id: "sc2", scene_title: "Ch 2" }] }),
    ]);
    const byId = get(mutationSetsByIdStore);
    expect(byId.get("s1")?.id).toBe("s1");
    expect(byId.get("s2")?.id).toBe("s2");
    const byAnchor = get(mutationSetByAnchorIdStore);
    expect(byAnchor.get("a1")?.id).toBe("s1");
    expect(byAnchor.get("a2")?.id).toBe("s2");
    expect(byAnchor.get("a3")?.id).toBe("s2");
    expect(byAnchor.get("nope")).toBeUndefined();
  });
});

describe("rosterLoaded (ADR-0095 §1: missing vs not-yet-loaded)", () => {
  it("starts false, and flips true after a refresh or a canonical-roster write", async () => {
    expect(get(mutationSetRosterLoadedStore)).toBe(false);
    vi.mocked(api.listMutationSetEntries).mockResolvedValue({ entries: [summary()] });
    await refreshMutationSetEntries();
    expect(get(mutationSetRosterLoadedStore)).toBe(true);
  });

  it("setMutationSetEntries (the delete write-through) also flips it true", () => {
    expect(get(mutationSetRosterLoadedStore)).toBe(false);
    setMutationSetEntries([summary()]);
    expect(get(mutationSetRosterLoadedStore)).toBe(true);
  });
});

describe("upsertMutationSet + mutationsVersion (ADR-0095 §1/§2)", () => {
  it("adds a brand-new set to the roster and bumps the version", () => {
    const before = mutationsVersion.value;
    upsertMutationSet(fullEntry({ id: "new-set" }));
    expect(get(mutationSetEntriesStore).map((e) => e.id)).toEqual(["new-set"]);
    expect(mutationsVersion.value).toBe(before + 1);
  });

  it("replaces an existing entry in place (a save relabels it at once)", () => {
    mutationSetEntriesStore.set([summary({ id: "s1", title: "Old title" })]);
    upsertMutationSet(fullEntry({ id: "s1", title: "New title" }));
    const roster = get(mutationSetEntriesStore);
    expect(roster).toHaveLength(1);
    expect(roster[0].title).toBe("New title");
  });

  it("derives row_count from `.rows.length` for a full entry", () => {
    upsertMutationSet(fullEntry({ id: "s1", rows: [{ id: "r1", field: "a", op: "replace", value: "x" }, { id: "r2", field: "b", op: "replace", value: "y" }] }));
    expect(get(mutationSetEntriesStore)[0].row_count).toBe(2);
  });

  it("removeMutationSetFromStore drops it and bumps the version", () => {
    mutationSetEntriesStore.set([summary({ id: "s1" }), summary({ id: "s2" })]);
    const before = mutationsVersion.value;
    removeMutationSetFromStore("s1");
    expect(get(mutationSetEntriesStore).map((e) => e.id)).toEqual(["s2"]);
    expect(mutationsVersion.value).toBe(before + 1);
  });

  it("setMutationSetEntries (delete's canonical-roster return) also bumps the version", () => {
    const before = mutationsVersion.value;
    setMutationSetEntries([summary({ id: "s2" })]);
    expect(mutationsVersion.value).toBe(before + 1);
  });
});
