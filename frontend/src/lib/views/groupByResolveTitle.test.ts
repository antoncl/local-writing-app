import { describe, expect, it } from "vitest";
import type { MetadataSchema, ViewSpec } from "@/lib/types";
import { evaluateView, type EvalNode } from "@/lib/views/evaluateView";
import { groupByHasRefLevel } from "@/lib/views/groupBy";

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
