import { describe, expect, it } from "vitest";
import { nodeSummary, type SummaryResolvers } from "./nodeSummary";
import type { ViewNodeData } from "./viewGraph";

// Resolvers that echo readable stand-ins so assertions read clearly.
const R: SummaryResolvers = {
  fieldName: (key) => ({ rank: "Rank", status: "Status", ref: "Ref", references: "References" })[key] ?? key,
  entryTypeName: (fqn) => ({ "lore:character": "Character", "lore:place": "Place" })[fqn] ?? fqn,
};

const summary = (kind: Parameters<typeof nodeSummary>[0], cfg: ViewNodeData) => nodeSummary(kind, cfg, R);

describe("nodeSummary — compact node one-liners (#220)", () => {
  it("shows placeholders for unconfigured predicates + structural slots", () => {
    // The predicate placeholders (type/tagged/field) surface through a Filter now —
    // the standalone predicate leaves are retired (#271/#284).
    expect(summary("filter", { filter_kind: "type" })).toBe("keep · — any type —");
    expect(summary("filter", { filter_kind: "tagged" })).toBe("keep · — tag —");
    expect(summary("filter", { filter_kind: "field" })).toBe("keep · — field —");
    expect(summary("nest", {})).toBe("— link field —");
    expect(summary("field_of", {})).toBe("— follow field —");
  });

  it("resolves a Filter's type / descendants_of / tagged predicate", () => {
    expect(summary("filter", { filter_kind: "type", type: "lore:character" })).toBe("keep · Character");
    expect(summary("filter", { filter_kind: "descendants_of", descendants_of: "lore:character" })).toBe("keep · Character +sub");
    expect(summary("filter", { filter_kind: "tagged", tagged: "hero" })).toBe("keep · #hero");
  });

  it("renders a Filter's field predicate with op + value", () => {
    expect(summary("filter", { filter_kind: "field", field: { key: "rank", op: "overlap", value: 3 } })).toBe("keep · Rank any of 3");
    expect(summary("filter", { filter_kind: "field", field: { key: "status", op: "disjoint", value: ["done", "wip"] } })).toBe(
      "keep · Status none of done, wip",
    );
    expect(summary("filter", { filter_kind: "field", field: { key: "rank", op: "set" } })).toBe("keep · Rank is set");
    expect(summary("filter", { filter_kind: "field", field: { key: "rank", op: "unset" } })).toBe("keep · Rank is empty");
  });

  it("resolves a select field's option value to its label (#1932)", () => {
    // The stored value is an opaque option id (e.g. a `layer` id); the compact
    // line must show the option's LABEL, the way the entry_type predicate already
    // resolves an FQN to a friendly name.
    const withOptions: SummaryResolvers = {
      ...R,
      optionLabel: (key, value) =>
        key === "layer" ? ({ a343657175dfade6: "unbecoming-someone" }[value] ?? value) : value,
    };
    expect(
      nodeSummary(
        "filter",
        { filter_kind: "field", field: { key: "layer", op: "overlap", value: "a343657175dfade6" } },
        withOptions,
      ),
    ).toBe("keep · layer any of unbecoming-someone");
    // Array (multi_select) values map element-wise.
    expect(
      nodeSummary(
        "filter",
        { filter_kind: "field", field: { key: "layer", op: "overlap", value: ["a343657175dfade6"] } },
        withOptions,
      ),
    ).toBe("keep · layer any of unbecoming-someone");
    // A non-option field (no match) keeps the raw value; a missing resolver too.
    expect(
      nodeSummary("filter", { filter_kind: "field", field: { key: "rank", op: "overlap", value: 3 } }, withOptions),
    ).toBe("keep · Rank any of 3");
  });

  // #2321: a reference field stores node ids (tags are nodes since ADR-0082), so
  // the compact line resolves them to titles instead of `tag_0980ba5721`.
  describe("reference values resolve to node titles (#2321)", () => {
    const withRefs: SummaryResolvers = {
      ...R,
      fieldName: (key) => (key === "tags" ? "Tags" : R.fieldName(key)),
      optionLabel: (key, value) => (key === "status" ? ({ draft: "Draft" }[value] ?? value) : value),
      refTitle: (id) => ({ tag_0980ba5721: "Villain", tag_2: "Hero", lore_1: "Lysandra" })[id],
    };
    const filter = (key: string, value: unknown) =>
      nodeSummary("filter", { filter_kind: "field", field: { key, op: "overlap", value } } as ViewNodeData, withRefs);

    it("names a referenced tag, singly and in a list", () => {
      expect(filter("tags", "tag_0980ba5721")).toBe("keep · Tags any of Villain");
      expect(filter("tags", ["tag_0980ba5721", "tag_2"])).toBe("keep · Tags any of Villain, Hero");
    });

    it("keeps an unknown id raw", () => {
      expect(filter("tags", ["tag_0980ba5721", "tag_gone"])).toBe("keep · Tags any of Villain, tag_gone");
    });

    it("prefers a select option's label over a node title", () => {
      expect(filter("status", "draft")).toBe("keep · Status any of Draft");
    });

    it("names the tag in a tagged predicate", () => {
      expect(nodeSummary("filter", { filter_kind: "tagged", tagged: "tag_2" } as ViewNodeData, withRefs)).toBe(
        "keep · #Hero",
      );
    });

    it("leaves values raw without a resolver (unchanged behaviour)", () => {
      expect(summary("filter", { filter_kind: "field", field: { key: "ref", op: "overlap", value: "lore_1" } })).toBe(
        "keep · Ref any of lore_1",
      );
    });
  });

  it("shows the parameter label for a promoted value slot", () => {
    const cfg: ViewNodeData = {
      filter_kind: "field",
      field: { key: "rank", op: "overlap", value: { var: "rank_n1" } },
      param: { name: "rank_n1", label: "Min rank", default: null },
    };
    expect(summary("filter", cfg)).toBe("keep · Rank any of ⟨Min rank⟩");
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

  it("resolves nest link and field_of projection", () => {
    expect(summary("nest", { match: { field: "ref", direction: "child_to_parent", by: "ref" } })).toBe("Ref");
    expect(summary("field_of", { project_field: "references" })).toBe("→ References");
  });

  it("formats boolean and projection operands", () => {
    expect(summary("filter", { filter_kind: "field", field: { key: "rank", op: "overlap", value: true } })).toBe("keep · Rank any of yes");
    expect(summary("filter", { filter_kind: "field", field: { key: "rank", op: "overlap", value: false } })).toBe("keep · Rank any of no");
    expect(
      summary("filter", { filter_kind: "field", field: { key: "ref", op: "overlap", value: { field_of: { of: {}, field: "x" } } } }),
    ).toBe("keep · Ref any of ⟨projection⟩");
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
    expect(summary("highlight", { color: "red" })).toBe("");
    expect(summary("output", {})).toBe("");
  });
});
