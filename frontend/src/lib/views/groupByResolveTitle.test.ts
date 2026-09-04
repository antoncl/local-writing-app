import { describe, expect, it } from "vitest";
import type { MetadataSchema, ViewSpec } from "@/lib/types";
import { evaluateView, type EvalNode } from "@/lib/views/evaluateView";
import { groupByHasRefLevel, viewUsesTagIds } from "@/lib/views/groupBy";

// ADR-0082 slice 1 §3: grouping by an `entity_ref_list` field whose value id
// is not in the view's own roster (a tag reference, most commonly — a scene
// view's roster is scenes, not tags) resolves the bucket label through
// `ctx.resolveTitle` instead of falling straight to the raw id. The
// `nodeById` (real-roster) path stays untouched — this is a FALLBACK, only
// consulted when the id isn't a roster member.
const SCHEMA = {
  version: 1,
  entry_types: {
    "manuscript:base": { name: "Manuscript", kind: "manuscript", abstract: true, fields: [] },
    "manuscript:scene": { name: "Scene", kind: "manuscript", parent: "manuscript:base", fields: [] },
  },
  fields: {
    title: { name: "Title", type: "text", category: "intrinsic" },
    entry_type: { name: "Type", type: "text", category: "intrinsic" },
    motifs: { name: "Motifs", type: "entity_ref_list" },
    status: { name: "Status", type: "select", options: [{ value: "draft", label: "Draft" }] },
  },
} as unknown as MetadataSchema;

const NODES: EvalNode[] = [
  { id: "scene_1", entry_type: "manuscript:scene", title: "Chapter one", metadata: { motifs: ["tag_1"] } },
];

const SPEC = {
  kind: "manuscript",
  expr: { descendants_of: "manuscript:base" },
  group_by: [{ field: "motifs" }],
} as ViewSpec;

describe("group_by ref bucket resolves an off-roster id through resolveTitle", () => {
  it("uses resolveTitle when the id is not in the view's own roster", () => {
    const result = evaluateView(SPEC, NODES, {
      schema: SCHEMA,
      resolveTitle: (id) => (id === "tag_1" ? "Coastal" : undefined),
    });
    const group = (result.groups ?? [])[0];
    expect(group?.label).toBe("Coastal");
    expect(group?.nodeId).toBe("tag_1");
  });

  it("falls back to the raw id when no resolveTitle is threaded", () => {
    const result = evaluateView(SPEC, NODES, { schema: SCHEMA });
    const group = (result.groups ?? [])[0];
    expect(group?.label).toBe("tag_1");
  });

  it("falls back to the raw id when resolveTitle itself has no answer", () => {
    const result = evaluateView(SPEC, NODES, { schema: SCHEMA, resolveTitle: () => undefined });
    const group = (result.groups ?? [])[0];
    expect(group?.label).toBe("tag_1");
  });
});

describe("group_by ref bucket folds a merged tag's id onto the survivor (ADR-0082 §5)", () => {
  const nodesBothIds: EvalNode[] = [
    { id: "scene_1", entry_type: "manuscript:scene", title: "Chapter one", metadata: { motifs: ["tag_mirror"] } },
    { id: "scene_2", entry_type: "manuscript:scene", title: "Chapter two", metadata: { motifs: ["tag_mirrors"] } },
  ];

  it("both a merged id and its survivor bucket under the SAME (survivor) key", () => {
    const result = evaluateView(SPEC, nodesBothIds, {
      schema: SCHEMA,
      resolveTitle: (id) => (id === "tag_mirrors" ? "mirrors" : undefined),
      canonicalId: (id) => (id === "tag_mirror" ? "tag_mirrors" : id),
    });
    const groups = result.groups ?? [];
    expect(groups).toHaveLength(1);
    expect(groups[0]?.nodeId).toBe("tag_mirrors");
    expect(groups[0]?.label).toBe("mirrors");
    expect(groups[0]?.children.map((c) => c.node?.id).sort()).toEqual(["scene_1", "scene_2"]);
  });

  it("is identity when no canonicalId is threaded", () => {
    const result = evaluateView(SPEC, NODES, { schema: SCHEMA, resolveTitle: () => "Coastal" });
    const group = (result.groups ?? [])[0];
    expect(group?.nodeId).toBe("tag_1");
  });
});

describe("groupByHasRefLevel — gates the reactive tag-roster subscription (review fix F7)", () => {
  it("is true when a group_by level's field is a node-set (entity_ref_list) field", () => {
    expect(groupByHasRefLevel(SPEC, SCHEMA)).toBe(true);
  });

  it("is false for an option-carrying level", () => {
    const spec = { ...SPEC, group_by: [{ field: "status" }] } as ViewSpec;
    expect(groupByHasRefLevel(spec, SCHEMA)).toBe(false);
  });

  it("is false for a plain text level", () => {
    const spec = { ...SPEC, group_by: [{ field: "title" }] } as ViewSpec;
    expect(groupByHasRefLevel(spec, SCHEMA)).toBe(false);
  });

  it("is false with no group_by at all", () => {
    const spec = { ...SPEC, group_by: undefined } as ViewSpec;
    expect(groupByHasRefLevel(spec, SCHEMA)).toBe(false);
    expect(groupByHasRefLevel(null, SCHEMA)).toBe(false);
  });
});

describe("viewUsesTagIds — widens the gate to a plain tagged: filter too (#1805)", () => {
  it("is true for a tagged: leaf with no group_by at all", () => {
    const spec = { kind: "lore", expr: { tagged: "tag_1" } } as ViewSpec;
    expect(viewUsesTagIds(spec, SCHEMA)).toBe(true);
  });

  it("is true for a tagged: leaf nested under set algebra", () => {
    const spec = {
      kind: "lore",
      expr: { intersect: [{ tagged: "tag_1" }, { type: "lore:note" }] },
    } as ViewSpec;
    expect(viewUsesTagIds(spec, SCHEMA)).toBe(true);
  });

  it("is true for a ref group_by level with no tagged: leaf (unchanged from groupByHasRefLevel)", () => {
    expect(viewUsesTagIds(SPEC, SCHEMA)).toBe(true);
  });

  // #1805 X2: the shipped assistant view's TAG param filter
  // (`field: {key: assistant_tags, op: overlap, value: {var: TAG}}`) has no
  // group_by AND no tagged: leaf — only a `field` predicate over a reference
  // field — so it needs its own arm of the gate.
  it("is true for a field predicate over a reference field, with no group_by or tagged: leaf", () => {
    const spec = { kind: "lore", expr: { field: { key: "motifs", op: "overlap", value: "tag_1" } } } as ViewSpec;
    expect(viewUsesTagIds(spec, SCHEMA)).toBe(true);
  });

  it("is false for a field predicate over a NON-reference field", () => {
    const spec = { kind: "lore", expr: { field: { key: "status", op: "overlap", value: "draft" } } } as ViewSpec;
    expect(viewUsesTagIds(spec, SCHEMA)).toBe(false);
  });

  it("is false when neither a tagged: leaf, a ref group_by level, nor a ref field predicate is present", () => {
    const spec = { kind: "lore", expr: { type: "lore:note" }, group_by: [{ field: "status" }] } as ViewSpec;
    expect(viewUsesTagIds(spec, SCHEMA)).toBe(false);
  });

  it("is false for an absent/null spec", () => {
    expect(viewUsesTagIds(null, SCHEMA)).toBe(false);
    expect(viewUsesTagIds(undefined, SCHEMA)).toBe(false);
  });

  // #1813: a Nest joined `by: "ref"` on a node-set field carries ids too —
  // `buildNestAdjacency` follows `canonicalId` for it, so the gate must catch it.
  it("is true for a nest joined by: ref on a node-set field", () => {
    const spec = {
      kind: "lore",
      expr: {
        nest: {
          parents: { type: "lore:note" },
          children: { type: "lore:note" },
          match: { field: "motifs", direction: "child_to_parent", by: "ref" },
        },
      },
    } as ViewSpec;
    expect(viewUsesTagIds(spec, SCHEMA)).toBe(true);
  });

  it("is false for the same nest joined by: ref on a NON-node-set field", () => {
    const spec = {
      kind: "lore",
      expr: {
        nest: {
          parents: { type: "lore:note" },
          children: { type: "lore:note" },
          match: { field: "status", direction: "child_to_parent", by: "ref" },
        },
      },
    } as ViewSpec;
    expect(viewUsesTagIds(spec, SCHEMA)).toBe(false);
  });

  it("is false for a nest joined by: title on a node-set field (a title join never carries an id)", () => {
    const spec = {
      kind: "lore",
      expr: {
        nest: {
          parents: { type: "lore:note" },
          children: { type: "lore:note" },
          match: { field: "motifs", direction: "child_to_parent", by: "title" },
        },
      },
    } as ViewSpec;
    expect(viewUsesTagIds(spec, SCHEMA)).toBe(false);
  });
});

describe("a plain tagged: filter with no ref grouping canonicalises through the widened gate (#1805)", () => {
  // The issue's main case: a saved view/plot filter whose ONLY tag touch is a
  // `tagged: <merged id>` leaf — no group_by at all — must still fold through
  // a merged tag's redirect when evaluated with a ctx gated by `viewUsesTagIds`
  // (mirroring how ViewNodeList.svelte/ViewBodyView.svelte now gate both
  // `resolveTitle` and `canonicalId`).
  const carrier: EvalNode = {
    id: "lore_a",
    entry_type: "lore:note",
    title: "Carrier",
    metadata: { tags: ["tag_survivor"] },
  };
  const spec = { kind: "lore", expr: { tagged: "tag_merged_old" } } as ViewSpec;
  const canonicalId = (id: string) => (id === "tag_merged_old" ? "tag_survivor" : id);

  it("selects the carrier when the gate gives evaluateView a canonicalId", () => {
    expect(viewUsesTagIds(spec, SCHEMA)).toBe(true);
    const result = evaluateView(spec, [carrier], { schema: SCHEMA, canonicalId });
    expect(result.nodes.map((n) => n.id)).toEqual(["lore_a"]);
  });

  it("selects nothing when the gate withholds canonicalId (the pre-widened behaviour)", () => {
    const result = evaluateView(spec, [carrier], { schema: SCHEMA });
    expect(result.nodes.map((n) => n.id)).toEqual([]);
  });
});
