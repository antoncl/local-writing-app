import { describe, expect, it } from "vitest";
import type { StructureDocument } from "@/lib/types";
import { structureToEvalNodes } from "./structureNodes";
import { evaluateView } from "./evaluateView";

function doc(): StructureDocument {
  return {
    root: {
      id: "root",
      type: "root",
      title: "Manuscript",
      children: [
        {
          id: "act1",
          type: "scene:act",
          title: "Act One",
          computed_metadata: { number: 1 },
          children: [
            {
              id: "s1",
              type: "scene:scene",
              title: "Arrival",
              scene_id: "s1",
              status: "complete",
              color: "moss",
              metadata: { pov: "char_alice", color: "moss" },
              computed_metadata: { number: 1, word_count: 42 },
              children: [],
            },
            {
              id: "s2",
              type: "scene:scene",
              title: "Departure",
              scene_id: "s2",
              status: "draft",
              metadata: { pov: "char_bob" },
              computed_metadata: { number: 2 },
              children: [],
            },
          ],
        },
      ],
    },
  };
}

describe("structureToEvalNodes (#184 Phase 3 roster enrichment)", () => {
  it("merges full scene metadata + computed counters + status into one filterable dict", () => {
    const nodes = structureToEvalNodes(doc());
    const s1 = nodes.find((n) => n.id === "s1")!;
    expect(s1.metadata).toEqual({ pov: "char_alice", color: "moss", number: 1, word_count: 42, status: "complete" });
    // ancestry still carries the container chain for tree presentation.
    expect(s1.ancestry).toEqual([{ key: "act1", label: "Act One", nodeId: "act1" }]);
  });

  it("omits status when the node has none (containers)", () => {
    const nodes = structureToEvalNodes(doc());
    const act = nodes.find((n) => n.id === "act1")!;
    expect(act.metadata).toEqual({ number: 1 });
    expect("status" in (act.metadata ?? {})).toBe(false);
  });

  it("lets a scene view filter the roster by status (the Draft filter this enables)", () => {
    const nodes = structureToEvalNodes(doc());
    const result = evaluateView(
      { kind: "scene", expr: { field: { key: "status", op: "overlap", value: "complete" } }, sort: { by: "manual" } },
      nodes,
    );
    expect(result.nodes.map((n) => n.id)).toEqual(["s1"]);
  });

  it("lets a scene view filter the roster by pov (entity_ref, id-compared)", () => {
    const nodes = structureToEvalNodes(doc());
    const result = evaluateView(
      { kind: "scene", expr: { field: { key: "pov", op: "overlap", value: "char_bob" } }, sort: { by: "manual" } },
      nodes,
    );
    expect(result.nodes.map((n) => n.id)).toEqual(["s2"]);
  });
});

// #201: a scene's roster id is its structure `node.id`, but the reverse
// reference index keys scenes by their canonical `scene_id`. A `references`
// projection over the Draft roster must bridge the two, or it silently misses
// every scene. This doc keeps the two id spaces DISTINCT (unlike `doc()` above,
// which reuses one value for both) so the bridge is actually exercised.
function draftDoc(): StructureDocument {
  return {
    root: {
      id: "root",
      type: "root",
      title: "Manuscript",
      children: [
        {
          id: "node_act",
          type: "scene:act",
          title: "Act One",
          computed_metadata: { number: 1 },
          children: [
            { id: "node_s1", type: "scene:scene", title: "Scene 1", scene_id: "scene_s1", status: "draft", metadata: {}, computed_metadata: { number: 1 }, children: [] },
            { id: "node_s2", type: "scene:scene", title: "Scene 2", scene_id: "scene_s2", status: "draft", metadata: {}, computed_metadata: { number: 2 }, children: [] },
          ],
        },
      ],
    },
  };
}

describe("structureToEvalNodes — references over the Draft roster (#201 id-space bridge)", () => {
  it("carries a scene's canonical scene_id as ref_id (containers omit it)", () => {
    const nodes = structureToEvalNodes(draftDoc());
    expect(nodes.find((n) => n.id === "node_s1")!.ref_id).toBe("scene_s1");
    expect(nodes.find((n) => n.id === "node_act")!.ref_id).toBeUndefined();
  });

  it("field_of(scene, references) returns the referrer scene despite node.id ≠ scene_id", () => {
    const nodes = structureToEvalNodes(draftDoc());
    // Scene 2 references Scene 1 → the CANONICAL-keyed reverse index maps
    // scene_s1 → {scene_s2}. The projection must translate node_s1 → scene_s1
    // for the lookup, then scene_s2 → node_s2 for the roster universe filter.
    const referenceIndex = new Map([["scene_s1", new Set(["scene_s2"])]]);
    const result = evaluateView(
      { kind: "scene", expr: { field_of: { of: { hand_picked: ["node_s1"] }, field: "references" } }, sort: { by: "manual" } },
      nodes,
      { referenceIndex },
    );
    expect(result.nodes.map((n) => n.id)).toEqual(["node_s2"]);
  });

  it("field_of($self, references) bridges regardless of which id space $self is bound in", () => {
    const nodes = structureToEvalNodes(draftDoc());
    const referenceIndex = new Map([["scene_s1", new Set(["scene_s2"])]]);
    const spec = { kind: "scene", expr: { field_of: { of: { var: "$self" }, field: "references" } }, sort: { by: "manual" as const } };
    // Bound to the roster id (node_…) → translated via ref_id; bound to the
    // canonical id (scene_…) → looked up directly. Both must resolve the referrer.
    const byRosterId = evaluateView(spec, nodes, { referenceIndex, bindings: { $self: ["node_s1"] } });
    const byCanonical = evaluateView(spec, nodes, { referenceIndex, bindings: { $self: ["scene_s1"] } });
    expect(byRosterId.nodes.map((n) => n.id)).toEqual(["node_s2"]);
    expect(byCanonical.nodes.map((n) => n.id)).toEqual(["node_s2"]);
  });
});
