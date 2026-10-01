// Pure-logic test for a scene move's slot (ADR-0097 §8): the move API counts the position
// with the moved node removed from its old place, and undo needs where the scene sat.
import { describe, expect, it } from "vitest";
import { planSceneMove } from "./sceneMove";
import type { StructureDocument, StructureNode } from "@/lib/types";

const scene = (id: string): StructureNode => ({ id: `n_${id}`, scene_id: id, type: "s", title: id, children: [] });
const group = (id: string, children: StructureNode[]): StructureNode => ({ id, type: "c", title: id, children });
const doc = (): StructureDocument =>
  ({ root: group("root", [group("ch1", [scene("s1"), scene("s2"), scene("s3")]), group("ch2", [scene("s4")])]) }) as unknown as StructureDocument;

describe("planSceneMove", () => {
  it("moves into another chapter after a neighbour, remembering where the scene sat", () => {
    expect(planSceneMove(doc(), "s2", "ch2", { after: "s4" })).toEqual({
      nodeId: "n_s2",
      from: { parentId: "ch1", position: 1 },
      to: { parentId: "ch2", position: 1 },
    });
  });

  it("moves before a neighbour, and to the end with no neighbour", () => {
    expect(planSceneMove(doc(), "s2", "ch2", { before: "s4" })!.to).toEqual({ parentId: "ch2", position: 0 });
    expect(planSceneMove(doc(), "s2", "ch2", null)!.to).toEqual({ parentId: "ch2", position: 1 });
  });

  it("counts the slot with the scene removed when it moves within its own chapter", () => {
    // [s1 s2 s3] → s1 after s3: the list without s1 is [s2 s3], so after s3 is position 2.
    expect(planSceneMove(doc(), "s1", "ch1", { after: "s3" })!.to).toEqual({ parentId: "ch1", position: 2 });
    expect(planSceneMove(doc(), "s3", "ch1", { before: "s1" })!.to).toEqual({ parentId: "ch1", position: 0 });
  });

  it("is null when the scene already sits there", () => {
    expect(planSceneMove(doc(), "s2", "ch1", { after: "s1" })).toBeNull();
    expect(planSceneMove(doc(), "s3", "ch1", null)).toBeNull();
  });

  it("is null for a scene or parent the tree does not hold", () => {
    expect(planSceneMove(doc(), "nope", "ch1", null)).toBeNull();
    expect(planSceneMove(doc(), "s1", "nope", null)).toBeNull();
    expect(planSceneMove(null, "s1", "ch1", null)).toBeNull();
  });

  it("appends when the neighbour is not a child of the target", () => {
    expect(planSceneMove(doc(), "s1", "ch2", { after: "s2" })!.to).toEqual({ parentId: "ch2", position: 1 });
  });
});
