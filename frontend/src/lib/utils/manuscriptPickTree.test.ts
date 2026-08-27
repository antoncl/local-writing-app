import { describe, expect, it } from "vitest";
import type { NodePickerRef, StructureDocument, StructureNode } from "@/lib/types";
import {
  flattenManuscript,
  refForNode,
  sceneCountForRef,
  togglePickAt,
  type PickState,
} from "./manuscriptPickTree";

// root
// ├─ Act A            (node "A")
// │  ├─ Ch 1          (node "C1")
// │  │  ├─ Scene 1    (node "n1", scene_id "s1")
// │  │  └─ Scene 2    (node "n2", scene_id "s2")
// │  └─ Ch 2          (node "C2")
// │     ├─ Scene 3    (node "n3", scene_id "s3")
// │     └─ Scene 4    (node "n4", scene_id "s4")
// └─ Act B            (node "B")
//    └─ Scene 5       (node "n5", scene_id "s5")
function scene(id: string, sceneId: string, title: string): StructureNode {
  return { id, type: "manuscript:scene", title, scene_id: sceneId, children: [] } as StructureNode;
}
function container(id: string, type: string, title: string, children: StructureNode[]): StructureNode {
  return { id, type, title, children } as StructureNode;
}
function doc(): StructureDocument {
  return {
    root: container("root", "root", "The Manuscript", [
      container("A", "manuscript:act", "Act A", [
        container("C1", "manuscript:chapter", "Ch 1", [scene("n1", "s1", "Scene 1"), scene("n2", "s2", "Scene 2")]),
        container("C2", "manuscript:chapter", "Ch 2", [scene("n3", "s3", "Scene 3"), scene("n4", "s4", "Scene 4")]),
      ]),
      container("B", "manuscript:act", "Act B", [scene("n5", "s5", "Scene 5")]),
    ]),
  } as StructureDocument;
}

const NONE = new Set<string>();
function states(value: NodePickerRef[]): Record<string, PickState> {
  const rows = flattenManuscript(doc(), value, NONE);
  return Object.fromEntries(rows.map((r) => [r.id, r.state]));
}
function ids(value: NodePickerRef[]): string[] {
  return value.filter((r) => r.kind === "manuscript").map((r) => r.id).sort();
}

describe("manuscriptPickTree — state", () => {
  it("everything off when nothing is picked", () => {
    const s = states([]);
    expect(new Set(Object.values(s))).toEqual(new Set(["off"]));
  });

  it("a single scene pick makes its ancestors indeterminate", () => {
    const s = states([{ id: "s1", kind: "manuscript", entry_type: "manuscript:scene", title: "Scene 1" }]);
    expect(s.n1).toBe("on");
    expect(s.n2).toBe("off");
    expect(s.C1).toBe("indeterminate");
    expect(s.A).toBe("indeterminate");
    expect(s.root).toBe("indeterminate");
    expect(s.B).toBe("off");
  });

  it("a container ref makes its descendants implied", () => {
    const s = states([{ id: "C1", kind: "manuscript", entry_type: "manuscript:chapter", title: "Ch 1" }]);
    expect(s.C1).toBe("on");
    expect(s.n1).toBe("implied");
    expect(s.n2).toBe("implied");
    expect(s.A).toBe("indeterminate");
    expect(s.root).toBe("indeterminate");
  });
});

describe("manuscriptPickTree — absorb", () => {
  it("checking a chapter drops its scene refs and stores one container ref", () => {
    const start = [
      { id: "s1", kind: "manuscript" as const, entry_type: "manuscript:scene", title: "Scene 1" },
      { id: "s2", kind: "manuscript" as const, entry_type: "manuscript:scene", title: "Scene 2" },
    ];
    const next = togglePickAt(doc(), start, "C1");
    expect(ids(next)).toEqual(["C1"]);
    expect(states(next).C1).toBe("on");
    expect(states(next).n1).toBe("implied");
  });

  it("checking an act absorbs a nested chapter ref and scene refs beneath it", () => {
    const start = [
      { id: "C1", kind: "manuscript" as const, entry_type: "manuscript:chapter", title: "Ch 1" },
      { id: "s3", kind: "manuscript" as const, entry_type: "manuscript:scene", title: "Scene 3" },
    ];
    const next = togglePickAt(doc(), start, "A");
    expect(ids(next)).toEqual(["A"]);
  });

  it("checking the root absorbs everything into the whole-manuscript ref", () => {
    const start = [{ id: "C2", kind: "manuscript" as const, entry_type: "manuscript:chapter", title: "Ch 2" }];
    const next = togglePickAt(doc(), start, "root");
    expect(ids(next)).toEqual(["root"]);
    const s = states(next);
    expect(s.root).toBe("on");
    expect(s.n1).toBe("implied");
    expect(s.n5).toBe("implied");
  });
});

describe("manuscriptPickTree — split", () => {
  it("unchecking an implied scene splits the chapter into its other scenes", () => {
    const start = [{ id: "C1", kind: "manuscript" as const, entry_type: "manuscript:chapter", title: "Ch 1" }];
    const next = togglePickAt(doc(), start, "n1"); // n1 is implied via C1
    expect(ids(next)).toEqual(["s2"]); // chapter gone, sibling scene explicit
    const s = states(next);
    expect(s.n1).toBe("off");
    expect(s.n2).toBe("on");
    expect(s.C1).toBe("indeterminate");
  });

  it("unchecking a scene under the root demotes to siblings at each level", () => {
    const start = [{ id: "root", kind: "manuscript" as const, entry_type: "root", title: "The Manuscript" }];
    const next = togglePickAt(doc(), start, "n1");
    // path root→A→C1→n1: keep act B, chapter C2, scene s2; drop the path to n1.
    expect(ids(next)).toEqual(["B", "C2", "s2"]);
    const s = states(next);
    expect(s.n1).toBe("off");
    expect(s.n2).toBe("on");
    expect(s.C2).toBe("on");
    expect(s.B).toBe("on");
    expect(s.root).toBe("indeterminate");
  });
});

describe("manuscriptPickTree — search filter", () => {
  it("keeps only matching scenes plus the containers on their path, expanded", () => {
    // Match scene "s3" (under Act A → Ch 2). Expect root, A, C2, n3 — not C1,
    // not Act B, and collapse is ignored (expandAll).
    const rows = flattenManuscript(doc(), [], new Set(["A", "C2"]), {
      sceneVisible: (n) => n.scene_id === "s3",
      expandAll: true,
    });
    expect(rows.map((r) => r.id)).toEqual(["root", "A", "C2", "n3"]);
  });

  it("emits nothing when no scene matches", () => {
    const rows = flattenManuscript(doc(), [], new Set(), { sceneVisible: () => false });
    expect(rows).toEqual([]);
  });

  it("honors the scene-subtype allowlist while keeping collapse (no search)", () => {
    // Allow only s1 (a "battle" subtype, say). Collapse is still honored for the
    // containers that survive, and disallowed scenes / empty containers drop.
    const rows = flattenManuscript(doc(), [], new Set(["C1"]), {
      sceneVisible: (n) => n.scene_id === "s1",
    });
    // Only C1's subtree has s1; C2 and Act B drop. C1 is collapsed → its scene
    // row is hidden, but C1 itself shows (it has a visible descendant).
    expect(rows.map((r) => r.id)).toEqual(["root", "A", "C1"]);
    expect(rows.find((r) => r.id === "C1")?.collapsed).toBe(true);
  });
});

describe("manuscriptPickTree — toggle off and counts", () => {
  it("toggling a picked scene off removes it", () => {
    const start = [{ id: "s1", kind: "manuscript" as const, entry_type: "manuscript:scene", title: "Scene 1" }];
    expect(togglePickAt(doc(), start, "n1")).toEqual([]);
  });

  it("toggling a picked container off removes it", () => {
    const start = [{ id: "C1", kind: "manuscript" as const, entry_type: "manuscript:chapter", title: "Ch 1" }];
    expect(togglePickAt(doc(), start, "C1")).toEqual([]);
  });

  it("sceneCountForRef counts a container's descendants and ignores scenes", () => {
    const d = doc();
    expect(sceneCountForRef(d, { id: "C1", kind: "manuscript", title: "Ch 1" })).toBe(2);
    expect(sceneCountForRef(d, { id: "A", kind: "manuscript", title: "Act A" })).toBe(4); // two chapters × 2
    expect(sceneCountForRef(d, { id: "root", kind: "manuscript", title: "M" })).toBe(5);
    expect(sceneCountForRef(d, { id: "s1", kind: "manuscript", title: "Scene 1" })).toBeNull();
    expect(sceneCountForRef(d, { id: "l1", kind: "lore", title: "Lore" })).toBeNull();
  });

  it("refForNode builds scene vs container refs", () => {
    const s = refForNode(scene("n1", "s1", "Scene 1"));
    expect(s).toMatchObject({ id: "s1", kind: "manuscript", entry_type: "manuscript:scene" });
    const c = refForNode(container("C1", "manuscript:chapter", "Ch 1", []));
    expect(c).toMatchObject({ id: "C1", kind: "manuscript", entry_type: "manuscript:chapter" });
  });
});
