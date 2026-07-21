import { describe, expect, it } from "vitest";
import type { MetadataSchema } from "@/lib/types";
import type { EvalNode } from "@/lib/views/evaluateView";
import { evaluateView, groupBucketValue } from "@/lib/views/evaluateView";
import { leafGroup, nodeSet } from "@/lib/views/viewResult";

function node(id: string, title = id): EvalNode {
  return { id, entry_type: "lore:character", title };
}

describe("nodeSet", () => {
  it("wraps an array as the degenerate one-stream result", () => {
    const nodes = [node("a"), node("b")];
    const result = nodeSet(nodes);
    expect(result.nodes).toBe(nodes);
    expect(result.groups).toBeNull();
    expect(result.annotations.size).toBe(0);
  });
});

describe("leafGroup", () => {
  it("builds a childless real-node group keyed by node id", () => {
    const n = node("x", "Alice");
    const g = leafGroup(n);
    expect(g).toEqual({ key: "node:x", label: "Alice", color: null, nodeId: "x", node: n, children: [] });
  });

  it("carries a supplied color token", () => {
    expect(leafGroup(node("y"), "rose").color).toBe("rose");
  });
});

// A synthetic bucket's `key` is a RENDER key (`group:<value>`), so buckets and
// real nodes can share one map. Consumers reason in values. #333 shipped a
// consumer comparing against the bare value; every bucket drop silently did
// nothing while still painting the drop highlight, and no test noticed because
// nothing asserted what a consumer receives. These build the group through the
// real evaluator rather than by hand, so the namespacing can't drift out from
// under the helper.
describe("groupBucketValue (#333 — buckets speak values, not render keys)", () => {
  const SCHEMA = {
    version: 1,
    fields: { listed: { name: "Curation", type: "select", category: "stored", options: [] } },
    entry_types: { "lore:character": { name: "Character", kind: "lore" } },
  } as unknown as MetadataSchema;

  // The same field with a declared vocabulary — what `show_empty` reads.
  const OPTIONED = {
    ...SCHEMA,
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

  function grouped(values: string[]) {
    const nodes = values.map((v, i) => ({ ...node(`n${i}`), metadata: { listed: v } }));
    return evaluateView(
      { kind: "lore", expr: { descendants_of: "lore:character" }, group_by: [{ field: "listed" }] },
      nodes,
      { schema: SCHEMA },
    );
  }

  it("recovers the field value a bucket stands for", () => {
    const groups = grouped(["listed", "unlisted"]).groups!;
    expect(groups.map((g) => g.key)).toEqual(["group:listed", "group:unlisted"]);
    expect(groups.map(groupBucketValue)).toEqual(["listed", "unlisted"]);
  });

  it("returns null for a real-node group, which has an id and no value", () => {
    expect(groupBucketValue(leafGroup(node("x")))).toBeNull();
  });

  it("keeps working when show_empty synthesises a bucket no row landed in", () => {
    const groups = evaluateView(
      { kind: "lore", expr: { descendants_of: "lore:character" }, group_by: [{ field: "listed", show_empty: true }] },
      [{ ...node("n0"), metadata: { listed: "unlisted" } }],
      { schema: OPTIONED },
    ).groups!;
    expect(groups.map(groupBucketValue)).toEqual(["listed", "unlisted"]);
  });

  it("strips exactly one prefix, so a colon-bearing value survives", () => {
    // An entry_type FQN grouped on, or a tag literally named `group:x`.
    const groups = grouped(["lore:character", "group:x"]).groups!;
    expect(groups.map(groupBucketValue)).toEqual(["lore:character", "group:x"]);
  });
});
