// ADR-0037 CONFORMANCE SUITE — NORMATIVE.
//
// This file is the executable half of ADR-0037 (grouping is view algebra —
// `group_by` on the result, a row-preserving pipeline, the end of
// `ViewPresentation`). The ADR's Conformance section names it normative: where
// prose and this file disagree, THIS FILE wins until the ADR is amended.
//
// Protocol for implementers:
//  - `it(...)`       = ANCHOR: behavior that holds today and MUST keep holding
//                      through every ADR-0037 stage. Never weaken an anchor.
//  - `it.fails(...)` = SPEC: required ADR-0037 behavior not yet implemented.
//                      vitest passes it while the behavior is missing and
//                      FAILS THE SUITE the moment the behavior lands — flip it
//                      to `it(...)` in the same commit that implements it.
//                      Do NOT delete, reword, or "simplify" an assertion to
//                      make a stage pass; if an assertion looks wrong, stop
//                      and re-read the cited ADR section (and #196's lesson:
//                      verify claims against the spec, not the diff).
//
// Sections mirror the ADR: §2 group_by levels, §4 containment-as-relation,
// §5 row-preserving pipeline, §6 provenance/membership, §7 defaults.

import { describe, expect, it } from "vitest";
import type { MetadataSchema, ViewExpr, ViewSpec } from "@/lib/types";
import { defaultView, evaluateView, type EvalNode, type ViewGroup } from "@/lib/views/evaluateView";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

// The Paris world (the ADR's motivating example): locations, characters, and
// items; some live somewhere (`located_in` → a location id), some are
// universal/transient (no `located_in`). Roster order is load-bearing
// (manual sort == input order; first-seen bucket order derives from it).
const LORE: EvalNode[] = [
  { id: "paris", entry_type: "lore:location", title: "Paris", metadata: {} },
  { id: "marseille", entry_type: "lore:location", title: "Marseille", metadata: {} },
  { id: "amelie", entry_type: "lore:character", title: "Amelie", metadata: { located_in: "paris", rank: "k" } },
  { id: "bruno", entry_type: "lore:character", title: "Bruno", metadata: { located_in: "marseille", rank: "s" } },
  { id: "celine", entry_type: "lore:character", title: "Celine", metadata: { tags: ["hero", "royal"], rank: "k" } },
  { id: "dagger", entry_type: "lore:item", title: "Dagger", metadata: { located_in: "paris" } },
  { id: "elixir", entry_type: "lore:item", title: "Elixir", metadata: {} },
];

const LORE_SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", abstract: true, fields: [] },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base", fields: [] },
    "lore:item": { name: "Item", kind: "lore", parent: "lore:base", fields: [] },
    "lore:location": { name: "Location", kind: "lore", parent: "lore:base", fields: [] },
  },
  fields: {
    title: { name: "Title", type: "text", category: "intrinsic" },
    entry_type: { name: "Type", type: "text", category: "intrinsic" },
    id: { name: "ID", type: "text", category: "intrinsic" },
    located_in: { name: "Located in", type: "entity_ref" },
    tags: { name: "Tags", type: "tags" },
    // Select options carry {value, label}: a §2 select-level bucket is LABELLED
    // by the option label, keyed by the value.
    rank: { name: "Rank", type: "select", options: [{ value: "k", label: "Knight" }, { value: "s", label: "Soldier" }] },
  },
} as unknown as MetadataSchema;

// A manuscript-shaped roster where containment is an ORDINARY reference field
// (`parent`) — ADR-0037 §4: the structure files are just a materialized index
// of this relation, and the tree is a Nest over it.
const MS: EvalNode[] = [
  { id: "act1", entry_type: "scene:act", title: "Act 1", metadata: {} },
  { id: "ch1", entry_type: "scene:chapter", title: "Ch 1", metadata: { parent: "act1" } },
  { id: "ch2", entry_type: "scene:chapter", title: "Ch 2", metadata: { parent: "act1" } },
  { id: "s1", entry_type: "scene:scene", title: "Scene 1", metadata: { parent: "ch1", status: "draft" } },
  { id: "s2", entry_type: "scene:scene", title: "Scene 2", metadata: { parent: "ch1", status: "done" } },
];

const MS_SCHEMA = {
  version: 1,
  entry_types: {
    "scene:base": { name: "Scene", kind: "scene", abstract: true, fields: [] },
    "scene:act": { name: "Act", kind: "scene", parent: "scene:base", fields: [] },
    "scene:chapter": { name: "Chapter", kind: "scene", parent: "scene:base", fields: [] },
    "scene:scene": { name: "Scene", kind: "scene", parent: "scene:base", fields: [] },
  },
  fields: {
    title: { name: "Title", type: "text", category: "intrinsic" },
    entry_type: { name: "Type", type: "text", category: "intrinsic" },
    parent: { name: "Parent", type: "entity_ref" },
    status: { name: "Status", type: "select", options: [{ value: "draft", label: "Draft" }, { value: "done", label: "Done" }] },
  },
} as unknown as MetadataSchema;

// The containment Nest (§4): roots = parentless, children = the whole kind,
// join on the `parent` ref, recursive. This GRAMMAR FORM must hold whether the
// evaluator walks the relation or takes the ancestry fast-path.
const CONTAINMENT: ViewExpr = {
  nest: {
    parents: { field: { key: "parent", op: "unset" } },
    children: { descendants_of: "scene:base" },
    match: { field: "parent", direction: "child_to_parent", by: "ref" },
    recursive: true,
  },
};

const lore = (spec: Partial<ViewSpec>) => evaluateView({ kind: "lore", ...spec } as ViewSpec, LORE, { schema: LORE_SCHEMA });
const ms = (spec: Partial<ViewSpec>) => evaluateView({ kind: "scene", ...spec } as ViewSpec, MS, { schema: MS_SCHEMA });
const nodeIds = (r: { nodes: EvalNode[] }) => r.nodes.map((n) => n.id);

// Render a groups tree as nested labels: a childless group is its label (a
// leaf row or an empty container); a group with children is [label, [...]].
type Shape = string | [string, Shape[]];
const shape = <T extends EvalNode>(groups: ViewGroup<T>[] | null): Shape[] =>
  (groups ?? []).map((g) => (g.children.length === 0 ? (g.label ?? "?") : [g.label ?? "?", shape(g.children)]));

const ALL: ViewExpr = { descendants_of: "lore:base" };

// ---------------------------------------------------------------------------
// §2 — group_by: ν by attribute, on the result
// ---------------------------------------------------------------------------
describe("ADR-0037 §2: group_by levels", () => {
  it("ANCHOR: no group_by, no handles, flat pipeline → groups: null (flat is the absence of grouping)", () => {
    expect(lore({ expr: ALL }).groups).toBeNull();
  });

  it("one entry_type level → synthetic buckets labelled by type display name, first-seen order", () => {
    const r = lore({ expr: ALL, group_by: [{ field: "entry_type" }] });
    // Roster order: paris (Location) first, then amelie (Character), then dagger (Item).
    expect(shape(r.groups)).toEqual([
      ["Location", ["Paris", "Marseille"]],
      ["Character", ["Amelie", "Bruno", "Celine"]],
      ["Item", ["Dagger", "Elixir"]],
    ]);
    // Synthetic buckets: no node identity.
    for (const g of r.groups ?? []) expect(g.nodeId).toBeNull();
    // Membership is untouched by grouping (ADR-0027 §E): roster order, deduped.
    expect(nodeIds(r)).toEqual(["paris", "marseille", "amelie", "bruno", "celine", "dagger", "elixir"]);
  });

  it('order: "label" → alphabetical by bucket label', () => {
    const r = lore({ expr: ALL, group_by: [{ field: "entry_type", order: "label" }] });
    expect((r.groups ?? []).map((g) => g.label)).toEqual(["Character", "Item", "Location"]);
  });

  it('order: "label" sinks a bare (empty-value) row BELOW the sorted buckets (not interspersed)', () => {
    // amelie→Paris, bruno→Marseille, celine has no located_in. Under A–Z the
    // buckets sort (Marseille, Paris) and the bare row sinks to the bottom — an
    // out-of-sequence bare row amid alphabetized buckets reads as broken sorting.
    const r = lore({ expr: { type: "lore:character" }, group_by: [{ field: "located_in", order: "label" }] });
    expect(shape(r.groups)).toEqual([
      ["Marseille", ["Bruno"]],
      ["Paris", ["Amelie"]],
      "Celine",
    ]);
  });

  it("first-seen bucket order follows the view's sort (sort reorders rows → reorders buckets)", () => {
    const r = lore({ expr: ALL, sort: { by: "title", dir: "asc" }, group_by: [{ field: "entry_type" }] });
    // Titles asc: Amelie (Character) first, Dagger (Item) before Marseille (Location).
    expect((r.groups ?? []).map((g) => g.label)).toEqual(["Character", "Item", "Location"]);
  });

  it("a select level buckets by value, LABELLED by the option label", () => {
    const r = lore({ expr: { type: "lore:character" }, group_by: [{ field: "rank" }] });
    expect(shape(r.groups)).toEqual([
      ["Knight", ["Amelie", "Celine"]],
      ["Soldier", ["Bruno"]],
    ]);
  });

  it("a reference-field level → REAL-NODE buckets (openable headers); a missing value leaves the row bare at that level", () => {
    const r = lore({ expr: { type: "lore:character" }, group_by: [{ field: "located_in" }] });
    expect(shape(r.groups)).toEqual([
      ["Paris", ["Amelie"]],
      ["Marseille", ["Bruno"]],
      "Celine", // no located_in → bare beside the buckets, NOT an "Ungrouped" bucket
    ]);
    const parisBucket = (r.groups ?? [])[0];
    expect(parisBucket.nodeId).toBe("paris");
    expect(parisBucket.node?.id).toBe("paris");
    // §6: a field-origin header is a VALUE the algebra surfaced, not a member —
    // Paris is a bucket, not part of this view's membership.
    expect(nodeIds(r)).toEqual(["amelie", "bruno", "celine"]);
  });

  it("a multi-valued level fans a row out under each value; membership stays deduped (ADR-0027 §E)", () => {
    const r = lore({ expr: { hand_picked: ["celine"] }, group_by: [{ field: "tags" }] });
    expect(shape(r.groups)).toEqual([
      ["hero", ["Celine"]],
      ["royal", ["Celine"]],
    ]);
    expect(nodeIds(r)).toEqual(["celine"]);
  });

  it("levels nest in declared order (outer first)", () => {
    const r = lore({ expr: { type: "lore:character" }, group_by: [{ field: "entry_type" }, { field: "rank" }] });
    expect(shape(r.groups)).toEqual([
      ["Character", [
        ["Knight", ["Amelie", "Celine"]],
        ["Soldier", ["Bruno"]],
      ]],
    ]);
  });

  it("ANCHOR (Amd 1): with named groups, a top-level group_by is IGNORED — Organize is owned per-group", () => {
    // Pre-Amendment-1 this applied `rank` to BOTH handles. Amendment 1 makes
    // Organize a property of each group; a result-level group_by beside named
    // groups no longer exists (the designer emits it per-group), so it is ignored.
    const r = lore({
      groups: [
        { name: "Cast", expr: { type: "lore:character" } },
        { name: "Places", expr: { type: "lore:location" } },
      ],
      group_by: [{ field: "rank" }],
    });
    expect(shape(r.groups)).toEqual([
      ["Cast", ["Amelie", "Bruno", "Celine"]], // flat — top-level rank ignored
      ["Places", ["Paris", "Marseille"]],
    ]);
  });
});

// ---------------------------------------------------------------------------
// Amendment 1 — Organize is owned per-group
// ---------------------------------------------------------------------------
describe("ADR-0037 Amendment 1: per-group Organize", () => {
  it("ANCHOR: two groups organize INDEPENDENTLY — A by rank, B by location, same nodes", () => {
    const r = lore({
      groups: [
        { name: "By rank", expr: { type: "lore:character" }, group_by: [{ field: "rank" }] },
        { name: "By place", expr: { type: "lore:character" }, group_by: [{ field: "located_in" }] },
      ],
    });
    expect(shape(r.groups)).toEqual([
      ["By rank", [
        ["Knight", ["Amelie", "Celine"]],
        ["Soldier", ["Bruno"]],
      ]],
      ["By place", [
        ["Paris", ["Amelie"]],
        ["Marseille", ["Bruno"]],
        "Celine", // no located_in → bare within its group, §2 unchanged
      ]],
    ]);
    // Membership stays deduped across groups (ADR-0027 §E): each character once.
    expect(nodeIds(r)).toEqual(["amelie", "bruno", "celine"]);
  });

  it("ANCHOR: a group with its own levels nests; a sibling with none stays flat — handles outermost, per-group levels innermost", () => {
    const r = lore({
      groups: [
        { name: "Cast", expr: { type: "lore:character" }, group_by: [{ field: "rank" }] },
        { name: "Places", expr: { type: "lore:location" } }, // no levels → flat
      ],
    });
    expect(shape(r.groups)).toEqual([
      ["Cast", [
        ["Knight", ["Amelie", "Celine"]],
        ["Soldier", ["Bruno"]],
      ]],
      ["Places", ["Paris", "Marseille"]],
    ]);
  });

  it("ANCHOR: the single/unnamed group (expr + spec.group_by) is unchanged — Amendment 1 is additive", () => {
    // Byte-identical to the §2 entry_type anchor: the unnamed group keeps
    // `ViewSpec.group_by`; only named groups gained their own.
    const r = lore({ expr: ALL, group_by: [{ field: "entry_type" }] });
    expect(shape(r.groups)).toEqual([
      ["Location", ["Paris", "Marseille"]],
      ["Character", ["Amelie", "Bruno", "Celine"]],
      ["Item", ["Dagger", "Elixir"]],
    ]);
  });
});

// ---------------------------------------------------------------------------
// §6 — provenance: which buckets collapse, who is a member
// ---------------------------------------------------------------------------
describe("ADR-0037 §6: provenance rules", () => {
  it("a LONE group_by bucket keeps its header (declared grouping never collapses to flat)", () => {
    // A Lore project holding only characters must still show the "Character"
    // header — the day-one regression the ADR calls out.
    const r = lore({ expr: { type: "lore:character" }, group_by: [{ field: "entry_type" }] });
    expect(shape(r.groups)).toEqual([["Character", ["Amelie", "Bruno", "Celine"]]]);
  });

  it("ANCHOR: a lone HANDLE bucket still collapses to flat (its name is the list title, not a header)", () => {
    const r = lore({ groups: [{ name: "Everyone", expr: ALL }] });
    expect(r.groups).toBeNull();
    expect(nodeIds(r)).toEqual(["paris", "marseille", "amelie", "bruno", "celine", "dagger", "elixir"]);
  });
});

// ---------------------------------------------------------------------------
// §4 — containment is a relation; the manuscript tree is a Nest
// ---------------------------------------------------------------------------
describe("ADR-0037 §4: containment Nest", () => {
  it("ANCHOR: nest over the parent ref (roots = parent unset, recursive) reproduces the manuscript tree", () => {
    const r = ms({ expr: CONTAINMENT });
    expect(shape(r.groups)).toEqual([
      ["Act 1", [
        "Ch 2", // childless container: a leaf row, still visible
        ["Ch 1", ["Scene 1", "Scene 2"]],
      ]],
    ]);
    // Unfiltered: every placed node passes selection → all are members.
    expect(new Set(nodeIds(r))).toEqual(new Set(["act1", "ch1", "ch2", "s1", "s2"]));
  });

  it("orphans wired flat to the root — the routed equivalent of the retired keep (ADR-0028 Amdt 1)", () => {
    // The orphan output routed to an `All`-over-scope leaf: the unplaced children
    // rejoin the result as bare rows at the root. `ALL` inside `orphans` denotes
    // the orphan SET (the evaluator scopes the universe to it), so this reproduces
    // exactly what the retired `orphans: "keep"` scalar produced — now authorable.
    const r = lore({
      expr: {
        nest: {
          parents: { type: "lore:location" },
          children: ALL,
          match: { field: "located_in", direction: "child_to_parent", by: "ref" },
          orphans: ALL,
        },
      },
    });
    // Placed rows first (placement order), then orphans in roster order.
    expect(shape(r.groups)).toEqual([
      ["Paris", ["Amelie", "Dagger"]],
      ["Marseille", ["Bruno"]],
      "Celine",
      "Elixir",
    ]);
  });
});

// ---------------------------------------------------------------------------
// §5 — the row-preserving pipeline: σ over (node, path) rows
// ---------------------------------------------------------------------------
describe("ADR-0037 §5: row-preserving σ/∩/−", () => {
  it("filter AFTER nest: leaf test with path carried — ancestors revive from paths, empty branches self-prune", () => {
    const r = ms({ expr: { intersect: [CONTAINMENT, { field: { key: "status", op: "overlap", value: "draft" } }] } });
    // Ch 1 fails the filter itself but is revived by Scene 1's parent list;
    // Ch 2 and Scene 2 have no surviving row → gone.
    expect(shape(r.groups)).toEqual([["Act 1", [["Ch 1", ["Scene 1"]]]]]);
    // §6 σ-passage membership: only σ-passing nodes are members; revived
    // ancestors are context (Act 1 / Ch 1 carry no draft status → context).
    expect(nodeIds(r)).toEqual(["s1"]);
  });

  it("difference over rows removes σ-matching leaves, keeps the surviving structure", () => {
    const r = ms({ expr: { difference: { keep: CONTAINMENT, remove: { field: { key: "status", op: "overlap", value: "done" } } } } });
    expect(shape(r.groups)).toEqual([
      ["Act 1", [
        "Ch 2",
        ["Ch 1", ["Scene 1"]],
      ]],
    ]);
    // Everything surviving passes σ (nothing here is "done") → all members.
    expect(new Set(nodeIds(r))).toEqual(new Set(["act1", "ch1", "ch2", "s1"]));
  });

  it("intersect with a hand-picked node-set = leaf-membership σ, structure preserved", () => {
    const r = ms({ expr: { intersect: [CONTAINMENT, { hand_picked: ["s1", "ch2"] }] } });
    expect(shape(r.groups)).toEqual([
      ["Act 1", [
        "Ch 2",
        ["Ch 1", ["Scene 1"]],
      ]],
    ]);
    expect(nodeIds(r)).toEqual(["ch2", "s1"]);
  });

  it("ANCHOR: a container that is both a σ-passing member AND the parent of a surviving child appears exactly once (#101 merge-dedup)", () => {
    // ch1 is hand-picked (a member) AND parents the hand-picked s1. It must render
    // once — as the parent header carrying s1 — never twice (a leaf member row PLUS
    // a header). Migrated from the eradicated presentation:"tree" suite (#101);
    // §4/§5 otherwise only cover childless-container members and revived ancestors.
    const r = ms({ expr: { intersect: [CONTAINMENT, { hand_picked: ["ch1", "s1"] }] } });
    expect(shape(r.groups)).toEqual([["Act 1", [["Ch 1", ["Scene 1"]]]]]);
    // Act 1 is revived context (not picked); ch1 + s1 are the σ-passing members.
    expect(nodeIds(r)).toEqual(["ch1", "s1"]);
    // ch1 occurs exactly once across the tree — no double appearance.
    const act1 = r.groups![0];
    expect(act1.children.filter((g) => g.nodeId === "ch1")).toHaveLength(1);
  });

  it("ANCHOR: filter wired INTO nest's children participates in the join — chain-sensitive by design", () => {
    // Children restricted to scenes only: chapters are not in the children set,
    // so scenes cannot attach through them — they become orphans and (default
    // "drop") vanish. This is the OTHER wiring, and it must stay distinct from
    // filter-after-nest above. (Wiring IS the semantics — no modes.)
    const r = ms({
      expr: {
        nest: {
          parents: { field: { key: "parent", op: "unset" } },
          children: { type: "scene:scene" },
          match: { field: "parent", direction: "child_to_parent", by: "ref" },
          recursive: true,
        },
      },
    });
    expect(nodeIds(r)).toEqual(["act1"]);
    expect(r.diagnostics?.orphansDropped).toBe(2); // s1, s2 matched no parent in the children set
  });

  it("ANCHOR: union concatenates rows preserving each operand's paths", () => {
    const NOTE: EvalNode = { id: "note1", entry_type: "scene:scene", title: "Loose note", metadata: {} };
    const r = evaluateView(
      { kind: "scene", expr: { union: [CONTAINMENT, { hand_picked: ["note1"] }] } } as ViewSpec,
      // note1 is parentless, so the containment nest ALSO seeds it as a root
      // (a bare leaf row, path []) — identical to its hand-picked row, and the
      // union's (node, path) dedupe collapses the two into one.
      [...MS, NOTE],
      { schema: MS_SCHEMA },
    );
    // The nest's tree arrives grouped; the hand-picked note arrives flat (path
    // []), landing bare at the top level beside the tree.
    const top = shape(r.groups);
    expect(top).toContainEqual("Loose note");
    expect(top.some((s) => Array.isArray(s) && s[0] === "Act 1")).toBe(true);
  });

  it.todo("two row-producing operands in one combinator: the FIRST carries structure, later ones degrade to membership (§5, codified)");
});

// ---------------------------------------------------------------------------
// §2 + §4 + §5 — the flagship: the Paris view, end to end
// ---------------------------------------------------------------------------
describe("ADR-0037: the Paris view (nest + routed orphans + group_by)", () => {
  it("universal entities' type buckets sit beside city headers; each city re-groups by type", () => {
    const r = lore({
      expr: {
        nest: {
          parents: { type: "lore:location" },
          children: ALL,
          match: { field: "located_in", direction: "child_to_parent", by: "ref" },
          orphans: ALL, // routed flat (the retired keep); the outer group_by then buckets them by type
        },
      },
      group_by: [{ field: "entry_type" }],
    });
    expect(shape(r.groups)).toEqual([
      ["Paris", [
        ["Character", ["Amelie"]],
        ["Item", ["Dagger"]],
      ]],
      ["Marseille", [["Character", ["Bruno"]]]],
      ["Character", ["Celine"]],
      ["Item", ["Elixir"]],
    ]);
  });
});

// ---------------------------------------------------------------------------
// §7 — the defaults are honest views
// ---------------------------------------------------------------------------
describe("ADR-0037 §7: defaults", () => {
  it("the Lore default groups by entry_type (alphabetical labels)", () => {
    const spec = defaultView("lore", LORE_SCHEMA);
    expect(spec.group_by).toEqual([{ field: "entry_type", order: "label" }]);
  });

  it("the Assistants default groups by source layer", () => {
    const spec = defaultView("assistant", null);
    expect(spec.group_by?.[0]?.field).toBe("source_layer");
  });

  it("the Draft default is a recursive containment Nest — not a presentation flag", () => {
    const spec = defaultView("scene", MS_SCHEMA);
    expect(spec.expr?.nest?.recursive).toBe(true);
    expect((spec as { presentation?: unknown }).presentation).toBeUndefined();
  });
});
