import { describe, expect, it } from "vitest";
import { realizeLocations } from "./realizeLocations";
import type { StructureDocument, StructureNode } from "@/lib/types";

// Terse tree builder. A node with a "scene:scene" type is a leaf; anything else is
// a container. Only id/type/title/children matter to realizeLocations.
function node(id: string, type: string, title: string, children: StructureNode[] = []): StructureNode {
  return { id, type, title, children };
}
function doc(...children: StructureNode[]): StructureDocument {
  return { root: node("root", "root", "Manuscript", children) };
}

describe("realizeLocations", () => {
  it("returns nothing when the structure has not loaded", () => {
    expect(realizeLocations(null)).toEqual([]);
  });

  it("flattens containers in reading order with a depth per level, excluding scenes and the root", () => {
    const structure = doc(
      node("act1", "scene:act", "Act One", [
        node("ch1", "scene:chapter", "Chapter One", [node("s1", "scene:scene", "Opening")]),
        node("ch2", "scene:chapter", "Chapter Two", []),
      ]),
      node("act2", "scene:act", "Act Two", []),
      node("loose", "scene:scene", "A homeless scene"), // a scene directly under root
    );
    expect(realizeLocations(structure)).toEqual([
      { id: "act1", title: "Act One", depth: 0 },
      { id: "ch1", title: "Chapter One", depth: 1 },
      { id: "ch2", title: "Chapter Two", depth: 1 },
      { id: "act2", title: "Act Two", depth: 0 },
    ]);
  });

  it("yields an empty roster for a flat manuscript with only root-level scenes", () => {
    const structure = doc(node("s1", "scene:scene", "One"), node("s2", "scene:scene", "Two"));
    expect(realizeLocations(structure)).toEqual([]);
  });
});
