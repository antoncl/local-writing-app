import { describe, expect, it } from "vitest";
import { makeNodeSearchFilter, nodeTagTitles } from "./nodeSearch";

// A tag roster: id -> current title. Non-tag ids are simply absent.
const TAGS = new Map<string, string>([
  ["tag_1", "Continuity"],
  ["tag_2", "Dialogue"],
]);

describe("nodeTagTitles — field-agnostic tag-node resolution (#1816)", () => {
  it("resolves tag ids from any metadata field to their current titles", () => {
    // `assistant_tags` on an assistant, `tags` on a lore entry — both resolve.
    expect(nodeTagTitles({ assistant_tags: ["tag_1", "tag_2"] }, TAGS)).toEqual(["Continuity", "Dialogue"]);
    expect(nodeTagTitles({ tags: ["tag_2"] }, TAGS)).toEqual(["Dialogue"]);
  });

  it("drops ids the tag roster doesn't know (non-tag refs, stale ids)", () => {
    expect(nodeTagTitles({ location: ["lore_99"], assistant_tags: ["tag_1", "gone"] }, TAGS)).toEqual(["Continuity"]);
  });

  it("reads scalar, array, and member-record shapes; empty for no metadata", () => {
    expect(nodeTagTitles({ pinned_tag: "tag_1" }, TAGS)).toEqual(["Continuity"]);
    expect(nodeTagTitles({ refs: [{ id: "tag_2" }] }, TAGS)).toEqual(["Dialogue"]);
    expect(nodeTagTitles(null, TAGS)).toEqual([]);
  });
});

describe("makeNodeSearchFilter — title / #tag / alias matching (#1816)", () => {
  const filter = makeNodeSearchFilter(TAGS);
  const node = { title: "Copy Editor", metadata: { assistant_tags: ["tag_1"], aliases: ["Proofer"] } };

  it("empty query keeps every node", () => {
    expect(filter(node, "")).toBe(true);
  });

  it("plain query matches the title", () => {
    expect(filter(node, "copy")).toBe(true);
    expect(filter(node, "nope")).toBe(false);
  });

  it("plain query matches a tag title or an alias", () => {
    expect(filter(node, "continu")).toBe(true); // tag "Continuity"
    expect(filter(node, "proof")).toBe(true); // alias "Proofer"
  });

  it("#tag restricts the match to tag titles", () => {
    expect(filter(node, "#continu")).toBe(true);
    expect(filter(node, "#copy")).toBe(false); // title is not a tag
  });
});
