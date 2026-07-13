import { describe, expect, it } from "vitest";
import { nodeSummary, type SummaryResolvers } from "./nodeSummary";
import type { ViewNodeData } from "./viewGraph";

// Resolvers that echo readable stand-ins so assertions read clearly.
const R: SummaryResolvers = {
  fieldName: (key) => ({ rank: "Rank", status: "Status", ref: "Ref", references: "References" })[key] ?? key,
  entryTypeName: (fqn) => ({ "lore:character": "Character", "lore:place": "Place" })[fqn] ?? fqn,
  savedViewTitle: (id) => ({ v1: "Heroes" })[id] ?? id,
};

const summary = (kind: Parameters<typeof nodeSummary>[0], cfg: ViewNodeData) => nodeSummary(kind, cfg, R);

describe("nodeSummary — compact node one-liners (#220)", () => {
  it("shows placeholders for unconfigured leaves", () => {
    expect(summary("type", {})).toBe("— any type —");
    expect(summary("tagged", {})).toBe("— tag —");
    expect(summary("field", {})).toBe("— field —");
    expect(summary("view_ref", {})).toBe("— saved view —");
    expect(summary("nest", {})).toBe("— link field —");
    expect(summary("field_of", {})).toBe("— follow field —");
  });

  it("resolves type / descendants_of / tagged", () => {
    expect(summary("type", { type: "lore:character" })).toBe("Character");
    expect(summary("descendants_of", { descendants_of: "lore:character" })).toBe("Character +sub");
    expect(summary("tagged", { tagged: "hero" })).toBe("#hero");
  });

  it("renders field predicates with op + value", () => {
    expect(summary("field", { field: { key: "rank", op: "overlap", value: 3 } })).toBe("Rank any of 3");
    expect(summary("field", { field: { key: "status", op: "disjoint", value: ["done", "wip"] } })).toBe(
      "Status none of done, wip",
    );
    expect(summary("field", { field: { key: "rank", op: "set" } })).toBe("Rank is set");
    expect(summary("field", { field: { key: "rank", op: "unset" } })).toBe("Rank is empty");
  });

  it("shows the parameter label for a promoted value slot", () => {
    const cfg: ViewNodeData = {
      field: { key: "rank", op: "overlap", value: { var: "rank_n1" } },
      param: { name: "rank_n1", label: "Min rank", default: null },
    };
    expect(summary("field", cfg)).toBe("Rank any of ⟨Min rank⟩");
  });

  it("summarizes filter mode + inner predicate", () => {
    expect(summary("filter", { filter_mode: "keep", filter_kind: "tagged", tagged: "hero" })).toBe("keep · #hero");
    expect(summary("filter", { filter_mode: "drop", filter_kind: "type", type: "lore:place" })).toBe("drop · Place");
    expect(summary("filter", { filter_kind: "field", field: { key: "rank", op: "set" } })).toBe("keep · Rank is set");
  });

  it("summarizes multi-level sort as a key chain", () => {
    expect(summary("sorter", {})).toBe("manual order");
    expect(summary("sorter", { sort: { by: "manual" } })).toBe("manual order");
    expect(
      summary("sorter", { sort: { by: "title", dir: "asc", then: { by: "field", field_key: "rank", dir: "desc" } } }),
    ).toBe("title ↑, Rank ↓");
  });

  it("counts hand-picked nodes", () => {
    expect(summary("hand_picked", {})).toBe("none picked");
    expect(summary("hand_picked", { hand_picked: ["a"] })).toBe("1 node");
    expect(summary("hand_picked", { hand_picked: ["a", "b", "c"] })).toBe("3 nodes");
  });

  it("resolves view_ref, nest link, and field_of projection", () => {
    expect(summary("view_ref", { view_ref: "v1" })).toBe("Heroes");
    expect(summary("nest", { match: { field: "ref", direction: "child_to_parent", by: "ref" } })).toBe("Ref");
    expect(summary("field_of", { project_field: "references" })).toBe("→ References");
  });

  it("formats boolean and projection operands", () => {
    expect(summary("field", { field: { key: "rank", op: "overlap", value: true } })).toBe("Rank any of yes");
    expect(summary("field", { field: { key: "rank", op: "overlap", value: false } })).toBe("Rank any of no");
    expect(
      summary("field", { field: { key: "ref", op: "overlap", value: { field_of: { of: {}, field: "x" } } } }),
    ).toBe("Ref any of ⟨projection⟩");
  });

  it("handles a descendants_of inner filter", () => {
    expect(summary("filter", { filter_mode: "keep", filter_kind: "descendants_of", descendants_of: "lore:character" })).toBe(
      "keep · Character +sub",
    );
  });

  it("caps a cyclic sort chain instead of hanging", () => {
    const cyclic: import("./viewGraph").ViewNodeData["sort"] = { by: "title", dir: "asc" };
    (cyclic as { then?: unknown }).then = cyclic; // self-referential `then`
    // Must return within the 16-key cap rather than loop forever.
    expect(summary("sorter", { sort: cyclic }).startsWith("title ↑")).toBe(true);
  });

  it("returns no one-liner for structural nodes", () => {
    expect(summary("union", {})).toBe("");
    expect(summary("intersect", {})).toBe("");
    expect(summary("difference", {})).toBe("");
    expect(summary("complement", {})).toBe("");
    expect(summary("all", {})).toBe("");
    expect(summary("self", {})).toBe("");
    expect(summary("highlight", { color: "red" })).toBe("");
    expect(summary("output", {})).toBe("");
  });
});
