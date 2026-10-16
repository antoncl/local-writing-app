// DesignerRoster — the designer's schema-derived field roster + §F type
// inference, extracted from ViewBodyView (#2528). The inference algebra itself is
// pinned in lib/views/viewGraph.test.ts; these lock the roster layer on top of it:
// entry-type rosters, computed-field injection, cross-kind thinning, and that the
// derived values track the getters they were constructed with.
import { describe, expect, it } from "vitest";
import type { Edge, Node } from "@xyflow/svelte";
import type { MetadataSchema } from "@/lib/types";
import { OUTPUT_NODE_ID } from "@/lib/views/viewGraph";
import { DesignerRoster } from "./designerRoster.svelte";
import { toFlowNode, type FlowData } from "./hydrateView";

const schema = {
  fields: {
    title: { name: "Title", type: "text", category: "intrinsic" },
    role: { name: "Role", type: "text" },
    owner: {
      name: "Owner",
      type: "entity_ref",
      picker_config: { sources: [{ kind: "lore" }, { kind: "manuscript" }] },
    },
  },
  entry_types: {
    "lore:base": { name: "Base", kind: "lore", abstract: true, fields: ["title"] },
    "lore:character": { name: "Character", kind: "lore", fields: ["title", "role", "owner"] },
    "manuscript:scene": { name: "Scene", kind: "manuscript", fields: ["title"] },
  },
} as unknown as MetadataSchema;

const edge = (id: string, source: string, target: string): Edge =>
  ({ id, source, sourceHandle: "out", target, targetHandle: "in" }) as Edge;

function make(kind = "lore", nodes: Node<FlowData>[] = [], edges: Edge[] = []) {
  const state = { schema: schema as MetadataSchema | null, kind, nodes, edges };
  const roster = new DesignerRoster({
    getSchema: () => state.schema,
    getKind: () => state.kind,
    getNodes: () => state.nodes,
    getEdges: () => state.edges,
  });
  return { roster, state };
}

describe("DesignerRoster", () => {
  it("entryTypes is concrete-only; entryTypesWithAbstract adds the family roots", () => {
    const { roster } = make("lore");
    expect(roster.entryTypes.map((t) => t.fqn)).toEqual(["lore:character"]);
    expect(roster.entryTypesWithAbstract.map((t) => t.fqn)).toEqual(["lore:base", "lore:character"]);
  });

  it("re-derives when the kind getter's value changes", () => {
    const { roster, state } = make("lore");
    state.kind = "manuscript";
    expect(roster.entryTypes.map((t) => t.fqn)).toEqual(["manuscript:scene"]);
  });

  it("fields pins intrinsics first; structural kinds gain the computed `parent` ref", () => {
    const { roster } = make("manuscript");
    expect(roster.fields.map((f) => f.key)).toEqual(["parent", "title"]);
    expect(roster.fieldByKey("parent")?.type).toBe("entity_ref");
    // a schema field wins over a computed one; unknown keys on a plain kind are null
    expect(roster.fieldByKey("title")?.category).toBe("intrinsic");
    expect(make("lore").roster.fieldByKey("parent")).toBeNull();
  });

  it("a cross-kind input offers the shared fields (+ computed `parent`) and warns", () => {
    const nodes = [
      toFlowNode(OUTPUT_NODE_ID, "output", {}, { x: 1000, y: 0 }),
      toFlowNode("src", "hand_picked", { hand_picked: ["s1"] }, { x: 0, y: 0 }),
      toFlowNode("fo", "field_of", { project_field: "owner" }, { x: 100, y: 0 }),
      toFlowNode("sink", "filter", { filter_kind: "field" }, { x: 200, y: 0 }),
    ];
    const edges = [edge("e1", "src", "fo"), edge("e2", "fo", "sink"), edge("e3", "sink", OUTPUT_NODE_ID)];
    const { roster } = make("manuscript", nodes, edges);
    expect(roster.rosterWarningFor("sink")).toEqual({ kinds: ["lore", "manuscript"], thin: false });
    // only what every member shares survives (`role` is lore-only); the manuscript
    // kind's computed `parent` is prepended, which is why the roster isn't "thin"
    expect(roster.fieldsFor("sink").map((f) => f.key)).toEqual(["parent", "title"]);
    // a single-kind input (the source itself) raises no warning and uses the anchor roster
    expect(roster.rosterWarningFor("fo")).toBeNull();
  });

  it("inferenceGraph indexes the live canvas nodes by id", () => {
    const { roster } = make("lore", [toFlowNode("a", "all", {}, { x: 0, y: 0 })]);
    expect([...roster.inferenceGraph.byId.keys()]).toEqual(["a"]);
  });
});
