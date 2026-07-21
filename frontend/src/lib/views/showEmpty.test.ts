import { describe, expect, it } from "vitest";
import type { MetadataSchema } from "@/lib/types";
import type { EvalNode } from "@/lib/views/evaluateView";
import { evaluateView } from "@/lib/views/evaluateView";

// #333: `show_empty` renders a level's whole declared vocabulary. Default OFF,
// because empty-bucket pruning is what stops a scene view sprouting a bucket per
// unused status — the opt-in exists for a curation axis, where the empty bucket
// is the one you need to act on.
const CURATION = {
  version: 1,
  entry_types: { "assistant:assistant": { name: "Assistant", kind: "assistant" } },
  fields: {
    listed: {
      name: "Curation",
      type: "select",
      category: "stored",
      options: [
        { value: "listed", label: "Active" },
        { value: "unlisted", label: "Unlisted" },
      ],
    },
  },
} as unknown as MetadataSchema;

function assistant(id: string, listed: string): EvalNode {
  return { id, entry_type: "assistant:assistant", title: id, metadata: { listed } };
}

const ROSTER = { descendants_of: "assistant:assistant" };

function labels(nodes: EvalNode[], show_empty?: boolean): (string | null)[] {
  const result = evaluateView(
    { kind: "assistant", expr: ROSTER, group_by: [{ field: "listed", ...(show_empty ? { show_empty } : {}) }] },
    nodes,
    { schema: CURATION },
  );
  return (result.groups ?? []).map((g) => g.label);
}

describe("group_by show_empty", () => {
  it("is off by default — a value no row carries produces no bucket", () => {
    expect(labels([assistant("a", "listed")])).toEqual(["Active"]);
  });

  it("shows the whole vocabulary when opted in", () => {
    expect(labels([assistant("a", "listed")], true)).toEqual(["Active", "Unlisted"]);
  });

  it("shows an empty ACTIVE bucket when nothing is listed — the case it exists for", () => {
    // Without this there is no Active bucket, so the drag that would fill it has
    // no target and the roster cannot be curated from a standing start.
    const groups = evaluateView(
      { kind: "assistant", expr: ROSTER, group_by: [{ field: "listed", show_empty: true }] },
      [assistant("a", "unlisted"), assistant("b", "unlisted")],
      { schema: CURATION },
    ).groups!;
    expect(groups.map((g) => g.label)).toEqual(["Active", "Unlisted"]);
    expect(groups[0].children).toEqual([]);
    expect(groups[1].children).toHaveLength(2);
  });

  it("orders by the declared vocabulary, not by which rows happen to exist", () => {
    // First-seen order would put Unlisted first here, purely because the only
    // rows are unlisted — a closed vocabulary on screen in full should not
    // reshuffle as content changes.
    expect(labels([assistant("a", "unlisted")], true)).toEqual(["Active", "Unlisted"]);
  });

  it("keeps values outside the vocabulary, after the declared ones", () => {
    expect(labels([assistant("a", "listed"), assistant("b", "bogus")], true)).toEqual([
      "Active",
      "Unlisted",
      "bogus",
    ]);
  });

  it("survives a row that has no value for the level", () => {
    // A row with no value stays BARE at this level — `buildLevel` makes it its
    // own member group with no `origin`. An earlier guard required every top
    // group to be a `field` bucket, so a single valueless row switched the whole
    // feature off, taking the empty Active bucket with it. The guard's real job
    // is only to detect a PIPELINE segment above the level.
    const groups = evaluateView(
      { kind: "assistant", expr: ROSTER, group_by: [{ field: "listed", show_empty: true }] },
      [
        assistant("a", "unlisted"),
        { id: "b", entry_type: "assistant:assistant", title: "No curation", metadata: {} },
      ],
      { schema: CURATION },
    ).groups!;
    expect(groups.map((g) => g.label)).toEqual(["Active", "Unlisted", "No curation"]);
    expect(groups[0].children).toEqual([]);
  });

  it("is inert when a pipeline segment sits above the level's buckets", () => {
    // `applyGroupBy` appends level segments AFTER whatever the pipeline produced,
    // so a nest puts its parents at the top and the level's buckets one deeper.
    // Filling the top there would prepend phantom Active/Unlisted buckets as
    // siblings of the nest's real parents. This is the case the guard exists for,
    // and the mutation that deleted it went unnoticed until this test was added.
    const nodes = [
      { id: "p", entry_type: "assistant:assistant", title: "Parent", metadata: { listed: "listed" } },
      { id: "c", entry_type: "assistant:assistant", title: "Child", metadata: { listed: "listed", parent: "p" } },
    ];
    const result = evaluateView(
      {
        kind: "assistant",
        expr: {
          nest: {
            parents: { filter: { of: ROSTER, pred: { field: { key: "parent", op: "unset" } } } },
            children: ROSTER,
            match: { field: "parent", direction: "child_to_parent", by: "ref" },
            recursive: true,
          },
        },
        group_by: [{ field: "listed", show_empty: true }],
      },
      nodes,
      { schema: CURATION },
    );
    // The nest's own parent is the top level; no synthesised buckets alongside it.
    expect(result.groups?.map((g) => g.label)).toEqual(["Parent"]);
  });

  it("is inert under a named handle, where the level's buckets are not the top", () => {
    // A named handle puts the level's buckets inside a handle strip, so filling
    // the TOP would invent siblings for the handle rather than for the level.
    // The flag fails closed there: `Unlisted` is NOT synthesised, even though the
    // same spec would synthesise it without the handle. (The lone handle is then
    // collapsed away by ADR-0037 §6's passthrough rule, which is why `Active`
    // surfaces at the top — the level's real bucket, not a filled one.)
    const result = evaluateView(
      {
        kind: "assistant",
        groups: [{ name: "All", expr: ROSTER, group_by: [{ field: "listed", show_empty: true }] }],
        sort: { by: "manual" },
      },
      [assistant("a", "listed")],
      { schema: CURATION },
    );
    expect(result.groups?.map((g) => g.label)).toEqual(["Active"]);
  });
});
