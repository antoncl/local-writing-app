// #1928 — the `layer` computed field. The backend declares a computed `select`
// field whose options are the project's inheritance layers; the frontend's only
// job is materializing its VALUE (the node's own `source_layer_id`) onto
// `computed_metadata.layer` at the eval boundary (`materializeLayerField`), so
// `fieldValue`/`groupBy` route it like any other computed select with no
// key-specific branch. See `evaluateView.ts` for the helper itself.

import { describe, expect, it } from "vitest";
import type { MetadataSchema, ViewSpec } from "@/lib/types";
import { evaluateView, materializeLayerField, type EvalNode } from "@/lib/views/evaluateView";

// A minimal resolved schema carrying `layer` exactly as the backend stamps it:
// a computed select field, options = the project's layers in rank order
// (ancestor before local).
const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", abstract: true, fields: [] },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base", fields: [] },
  },
  fields: {
    title: { name: "Title", type: "text", category: "intrinsic" },
    entry_type: { name: "Type", type: "text", category: "intrinsic" },
    layer: {
      name: "Layer",
      type: "computed",
      options: [
        { value: "L_anc", label: "Series" },
        { value: "L_local", label: "Book" },
      ],
      category: "computed",
      computed: { function: "layer", value_type: "select" },
    },
  },
} as unknown as MetadataSchema;

type SourceLayerNode = EvalNode & { source_layer_id?: string };

// Roster shape a real roster (LoreEntrySummary[]) carries: `source_layer_id`,
// no `computed_metadata.layer` yet — that's `materializeLayerField`'s job.
const RAW: SourceLayerNode[] = [
  { id: "ancestor", entry_type: "lore:character", title: "Ancestor Entry", metadata: {}, source_layer_id: "L_anc" },
  { id: "local", entry_type: "lore:character", title: "Local Entry", metadata: {}, source_layer_id: "L_local" },
];

describe("#1928 materializeLayerField", () => {
  it("stamps computed_metadata.layer from source_layer_id", () => {
    const [ancestor, local] = materializeLayerField(RAW);
    expect(ancestor.computed_metadata).toEqual({ layer: "L_anc" });
    expect(local.computed_metadata).toEqual({ layer: "L_local" });
  });

  it("leaves a node with no source_layer_id untouched (e.g. a scene)", () => {
    const scene: EvalNode = { id: "s1", entry_type: "manuscript:scene", title: "Scene 1", metadata: {} };
    const [out] = materializeLayerField([scene]);
    expect(out).toBe(scene); // no copy made
    expect(out.computed_metadata).toBeUndefined();
  });

  it("never clobbers an existing computed_metadata.layer", () => {
    const preset: SourceLayerNode = {
      id: "x",
      entry_type: "lore:character",
      title: "X",
      metadata: {},
      source_layer_id: "L_anc",
      computed_metadata: { layer: "already_set" },
    };
    const [out] = materializeLayerField([preset]);
    expect(out).toBe(preset);
    expect(out.computed_metadata).toEqual({ layer: "already_set" });
  });
});

describe("#1928 layer field routes through evaluateView like any computed select", () => {
  const NODES = materializeLayerField(RAW);

  it("filters via a field overlap predicate", () => {
    const r = evaluateView(
      { kind: "lore", expr: { field: { key: "layer", op: "overlap", value: "L_anc" } } } as ViewSpec,
      NODES,
      { schema: SCHEMA },
    );
    expect(r.nodes.map((n) => n.id)).toEqual(["ancestor"]);
  });

  it("groups by layer in declared-option order (ancestor before local)", () => {
    const r = evaluateView(
      { kind: "lore", expr: { descendants_of: "lore:base" }, group_by: [{ field: "layer" }] } as ViewSpec,
      NODES,
      { schema: SCHEMA },
    );
    expect((r.groups ?? []).map((g) => g.label)).toEqual(["Series", "Book"]);
  });
});
