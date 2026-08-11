import { describe, expect, it } from "vitest";
import type { PromptEntrySummary } from "@/lib/types";
import { buildPromptMenuTree, parseTitlePath, type MenuNode } from "./promptMenuTree";

// A prompt entry stub; only `title` and `id` matter to the tree builder.
function prompt(title: string, id = title): PromptEntrySummary {
  return {
    id,
    title,
    body: "",
    entry_type: "prompt",
    metadata: {},
    inputs: [],
  };
}

// Collapse a MenuNode tree to a compact shape for readable assertions: a leaf is
// its entry id string; a group is `{ label: [...children] }`.
function shape(nodes: MenuNode[]): unknown[] {
  return nodes.map((node) =>
    node.children.length > 0 ? { [node.label]: shape(node.children) } : node.entry?.id,
  );
}

describe("parseTitlePath (#832)", () => {
  it("splits, trims, and drops empty segments", () => {
    expect(parseTitlePath("A/B/C")).toEqual(["A", "B", "C"]);
    expect(parseTitlePath("A / B / C")).toEqual(["A", "B", "C"]);
    expect(parseTitlePath("A//B/")).toEqual(["A", "B"]);
    expect(parseTitlePath("/A")).toEqual(["A"]);
  });

  it("normalises spaced and unspaced separators identically", () => {
    expect(parseTitlePath("A / B / C")).toEqual(parseTitlePath("A/B/C"));
  });

  it("returns no segments for a degenerate title", () => {
    expect(parseTitlePath("/")).toEqual([]);
    expect(parseTitlePath("   ")).toEqual([]);
    expect(parseTitlePath("")).toEqual([]);
  });
});

describe("buildPromptMenuTree (#832)", () => {
  it("keeps slashless titles flat, sorted alpha (parity with the old menu)", () => {
    const tree = buildPromptMenuTree([prompt("Tone"), prompt("Expand"), prompt("Shorten")]);
    expect(shape(tree)).toEqual(["Expand", "Shorten", "Tone"]);
  });

  it("groups a shared prefix into a submenu", () => {
    const tree = buildPromptMenuTree([prompt("A/C"), prompt("A/B")]);
    expect(shape(tree)).toEqual([{ A: ["A/B", "A/C"] }]);
  });

  it("nests to arbitrary depth", () => {
    const tree = buildPromptMenuTree([prompt("A/B/C/D/E")]);
    expect(shape(tree)).toEqual([{ A: [{ B: [{ C: [{ D: ["A/B/C/D/E"] }] }] }] }]);
  });

  it("treats spaced and unspaced titles as the identical tree", () => {
    const spaced = shape(buildPromptMenuTree([prompt("A / B", "x"), prompt("A / C", "y")]));
    const tight = shape(buildPromptMenuTree([prompt("A/B", "x"), prompt("A/C", "y")]));
    expect(spaced).toEqual(tight);
  });

  it("makes a leaf that is also a parent a group with a self-leaf: A → {A, B}", () => {
    const tree = buildPromptMenuTree([prompt("A"), prompt("A/B")]);
    expect(shape(tree)).toEqual([{ A: ["A", "A/B"] }]);
  });

  it("keeps a degenerate title as a flat leaf under its raw title", () => {
    const tree = buildPromptMenuTree([prompt("/", "slash"), prompt("Tone", "tone")]);
    // "/" reduces to no segments → raw-title flat leaf; "/" sorts before "Tone".
    expect(shape(tree)).toEqual(["slash", "tone"]);
    expect(tree[0].label).toBe("/");
  });

  it("keeps two prompts with an identical title as separate reachable leaves", () => {
    const tree = buildPromptMenuTree([prompt("Dupe", "one"), prompt("Dupe", "two")]);
    // Duplicate titles become a group of same-labelled leaves — neither is lost.
    expect(shape(tree)).toEqual([{ Dupe: ["one", "two"] }]);
  });

  it("does not form empty groups: an absent (hidden) leaf leaves no branch", () => {
    // The builder only sees survivors of promptEntriesForSurface, so hiding "A/B"
    // just means it is not passed in — no dangling "A" group.
    const tree = buildPromptMenuTree([prompt("A/C")]);
    expect(shape(tree)).toEqual([{ A: ["A/C"] }]);
  });

  it("sorts groups and leaves together, alpha, per level", () => {
    const tree = buildPromptMenuTree([prompt("Zebra"), prompt("Apple/Pie"), prompt("Mango")]);
    expect(shape(tree)).toEqual([{ Apple: ["Apple/Pie"] }, "Mango", "Zebra"]);
  });
});
