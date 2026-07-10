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
