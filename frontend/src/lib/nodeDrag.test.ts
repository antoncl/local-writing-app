import { afterEach, describe, expect, it } from "vitest";
import type { MetadataSchema, NodePickerRef, StructureDocument, StructureNode } from "@/lib/types";
import { pickerMembership } from "@/lib/utils/pickerSources";
import {
  NODE_DND_MIME,
  clearNodeDrag,
  currentNodeDrag,
  dropPick,
  readNodeDrag,
  setNodeDrag,
  type DropPickOptions,
} from "./nodeDrag";

const SCHEMA = {
  entry_types: {
    "manuscript:container": { name: "Container", kind: "manuscript" },
    "manuscript:chapter": { name: "Chapter", kind: "manuscript", parent: "manuscript:container" },
    "manuscript:scene": { name: "Scene", kind: "manuscript" },
    "lore:character": { name: "Character", kind: "lore" },
    "lore:place": { name: "Place", kind: "lore" },
  },
  fields: {},
} as unknown as MetadataSchema;

const lore = (id: string, entry_type = "lore:character"): NodePickerRef => ({ id, kind: "lore", title: id, entry_type });
const scene = (sceneId: string): NodePickerRef => ({
  id: sceneId,
  kind: "manuscript",
  title: sceneId,
  entry_type: "manuscript:scene",
});

function opts(config: Parameters<typeof pickerMembership>[0], extra: Partial<DropPickOptions> = {}): DropPickOptions {
  return {
    membership: pickerMembership(config),
    schema: SCHEMA,
    excludeIds: [],
    multiple: config?.multiple !== false,
    structure: null,
    ...extra,
  };
}

const node = (id: string, type: string, children: StructureNode[], sceneId?: string): StructureNode =>
  ({ id, type, title: id, scene_id: sceneId, children, level: sceneId ? undefined : 1 }) as unknown as StructureNode;
// root > chapter "C1" (node) > scene "n1" (scene_id "s1"), "n2" ("s2")
const structure = {
  root: node("root", "root", [
    node("C1", "manuscript:chapter", [
      node("n1", "manuscript:scene", [], "s1"),
      node("n2", "manuscript:scene", [], "s2"),
    ]),
  ]),
} as unknown as StructureDocument;

describe("dropPick", () => {
  const loreOnly = { sources: [{ kind: "lore" }] };

  it("rejects a kind the input does not admit", () => {
    expect(dropPick([], scene("s1"), opts(loreOnly))).toBeNull();
  });

  it("rejects an entry_type outside the kind's whitelist", () => {
    const config = { sources: [{ kind: "lore", expr: { type: "lore:place" } }] };
    expect(dropPick([], lore("a"), opts(config))).toBeNull();
    expect(dropPick([], lore("p", "lore:place"), opts(config))).toEqual([lore("p", "lore:place")]);
  });

  it("rejects an excluded id", () => {
    expect(dropPick([], lore("a"), opts(loreOnly, { excludeIds: ["a"] }))).toBeNull();
  });

  it("changes nothing for an already-picked node (a drop never unpicks)", () => {
    expect(dropPick([lore("a")], lore("a"), opts(loreOnly))).toBeNull();
  });

  it("appends on a multi-select input", () => {
    expect(dropPick([lore("a")], lore("b"), opts(loreOnly))).toEqual([lore("a"), lore("b")]);
  });

  it("replaces on a single-select input", () => {
    expect(dropPick([lore("a")], lore("b"), opts({ ...loreOnly, multiple: false }))).toEqual([lore("b")]);
  });

  describe("manuscript", () => {
    const ms = { sources: [{ kind: "manuscript" }] };
    const chapter: NodePickerRef = { id: "C1", kind: "manuscript", title: "C1", entry_type: "manuscript:chapter" };

    it("picks a container as one live ref, absorbing picked children (togglePickAt)", () => {
      const out = dropPick([scene("s1")], chapter, opts(ms, { structure }));
      expect(out).toEqual([chapter]);
    });

    it("admits a container under a scene-type whitelist", () => {
      const only = { sources: [{ kind: "manuscript", expr: { type: "manuscript:scene" } }] };
      expect(dropPick([], chapter, opts(only, { structure }))).toEqual([chapter]);
    });

    it("never unpicks a scene covered by a picked container", () => {
      expect(dropPick([chapter], scene("s2"), opts(ms, { structure }))).toBeNull();
    });

    it("adds a scene not yet covered", () => {
      expect(dropPick([], scene("s2"), opts(ms, { structure }))?.map((r) => r.id)).toEqual(["s2"]);
    });
  });
});

describe("node drag payload", () => {
  afterEach(clearNodeDrag);

  function fakeEvent() {
    const store = new Map<string, string>();
    const dataTransfer = {
      effectAllowed: "uninitialized",
      setData: (type: string, data: string) => void store.set(type, data),
      getData: (type: string) => store.get(type) ?? "",
      get types() {
        return [...store.keys()];
      },
    };
    return { dataTransfer } as unknown as DragEvent;
  }

  it("round-trips the ref through the MIME and tracks the current drag", () => {
    const event = fakeEvent();
    setNodeDrag(event, lore("a"));
    expect(event.dataTransfer!.getData(NODE_DND_MIME)).toContain('"id":"a"');
    expect(currentNodeDrag(event)).toEqual(lore("a"));
    expect(readNodeDrag(event)).toEqual(lore("a"));
    expect(event.dataTransfer!.effectAllowed).toBe("copy");
    clearNodeDrag();
    expect(currentNodeDrag(event)).toBeNull();
  });

  it("widens a reorder drag's move to copyMove", () => {
    const event = fakeEvent();
    event.dataTransfer!.effectAllowed = "move";
    setNodeDrag(event, lore("a"));
    expect(event.dataTransfer!.effectAllowed).toBe("copyMove");
  });

  it("reads nothing from a foreign drag, even while a stale ref is held", () => {
    setNodeDrag(fakeEvent(), lore("stale")); // its dragend never fired
    expect(currentNodeDrag(fakeEvent())).toBeNull();
    expect(readNodeDrag(fakeEvent())).toBeNull();
  });
});
