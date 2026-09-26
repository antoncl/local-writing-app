// @vitest-environment happy-dom
// ADR-0095 §8: a linked set's stop names every place the edit will apply, in
// its caption, before the first keystroke.
import { afterEach, describe, expect, it } from "vitest";
import { render, screen } from "@/lib/test/component";
import MutationScrubber from "./MutationScrubber.svelte";
import { mutationSetEntriesStore, mutationSetRosterLoadedStore } from "@/lib/stores/mutationSets";
import type { MutationMarkerRecord, MutationSetEntrySummary } from "@/lib/types";
import type { MutationUnitGroup } from "@/lib/editor-core/mutationUnits";

afterEach(() => {
  mutationSetEntriesStore.set([]);
  mutationSetRosterLoadedStore.set(false);
});

function summary(over: Partial<MutationSetEntrySummary> = {}): MutationSetEntrySummary {
  return {
    id: "set1",
    title: "Promotion",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity: "mira",
    row_count: 1,
    rows: [{ id: "r1", field: "rank", op: "replace", value: "Captain" }],
    anchors: [],
    state: "active",
    pin_missing: false,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

function record(over: Partial<MutationMarkerRecord> = {}): MutationMarkerRecord {
  return {
    marker_id: "a1.r1",
    entity_id: "mira",
    field: "rank",
    op: "replace",
    value: "Captain",
    name: "",
    group: "",
    unit_id: "a1",
    unit_name: "",
    scene_id: "scene1",
    offset: 0,
    line: 0,
    scene_path: "Ch 1",
    set_id: "set1",
    anchor_id: "a1",
    row_id: "r1",
    ...over,
  };
}

function unit(over: Partial<MutationUnitGroup> = {}): MutationUnitGroup {
  return { unitId: "a1", name: "", records: [record()], ...over };
}

describe("MutationScrubber — linked stop caption (ADR-0095 §8)", () => {
  it("names the other places for a linked set", () => {
    mutationSetEntriesStore.set([
      summary({
        id: "set1",
        anchors: [
          { anchor_id: "a1", scene_id: "scene1", scene_title: "Ch 1" },
          { anchor_id: "a2", scene_id: "scene2", scene_title: "Ch 2" },
        ],
      }),
    ]);
    mutationSetRosterLoadedStore.set(true);

    render(MutationScrubber, {
      props: { units: [unit()], index: 1, onScrub: () => {}, stopEditable: true },
    });

    expect(
      screen.getByText("As of Ch 1 · editing this stop · linked — also in Ch 2"),
    ).toBeInTheDocument();
  });

  it("is unchanged for a single-anchor set", () => {
    mutationSetEntriesStore.set([
      summary({ id: "set1", anchors: [{ anchor_id: "a1", scene_id: "scene1", scene_title: "Ch 1" }] }),
    ]);
    mutationSetRosterLoadedStore.set(true);

    render(MutationScrubber, {
      props: { units: [unit()], index: 1, onScrub: () => {}, stopEditable: true },
    });

    expect(screen.getByText("As of Ch 1 · editing this stop")).toBeInTheDocument();
  });
});
