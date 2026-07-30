import { describe, expect, it } from "vitest";
import type { MetadataSchema } from "@/lib/types";
import {
  asSchemaKind,
  coerceStringList,
  isMetadataValuePresent,
  kindEntryTypeFqns,
  kindEntryTypeOptions,
  nestingLocalPrefix,
  normalizeListFieldValue,
  resolveSchemaScope,
  schemaKindForDocumentKind,
  SCHEMA_KIND_META,
  SCHEMA_KINDS,
  type NodeTypeTreeNode,
  type SchemaKind,
} from "@/lib/utils/schemaTypeHelpers";

// The entry_type roster shared by the view designer (ViewFlowNode pickers) and the
// runtime param strip (viewParams). `type` / `field → entry_type` want concrete
// types only; `descendants_of` wants abstract family roots too (#293/#295).
const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", abstract: true },
    "lore:character": { name: "Character", kind: "lore" },
    "lore:place": { name: "Place", kind: "lore" },
    "scene:scene": { name: "Scene", kind: "scene" },
  },
  fields: {},
} as unknown as MetadataSchema;

describe("SCHEMA_KIND_META / SCHEMA_KINDS / asSchemaKind (the kind cascade — #729)", () => {
  it("includes plot with the right tab label, heading and default type", () => {
    expect(SCHEMA_KINDS).toContain("plot");
    expect(SCHEMA_KIND_META.plot).toEqual({ label: "Plot", heading: "Plot Types", defaultType: "plot:plotline" });
  });

  it("SCHEMA_KINDS is exactly the table's keys, in order", () => {
    // The tab strip renders from SCHEMA_KINDS and the SchemaPanes cascade reads
    // SCHEMA_KIND_META — driving both off one object is what stops them drifting.
    expect(SCHEMA_KINDS).toEqual(Object.keys(SCHEMA_KIND_META));
  });

  it("round-trips every kind through asSchemaKind — the derivation the Plot tab relies on", () => {
    // SchemaPanes derives schemaFieldKind as `asSchemaKind(type.kind) ?? \"scene\"`.
    // The shipped bug was plot NOT round-tripping (a ternary dropped it to scene),
    // which silently scoped the Plot tab to the Scene tree. Pin every kind.
    for (const kind of SCHEMA_KINDS) {
      expect(asSchemaKind(kind)).toBe(kind);
      expect(SCHEMA_KIND_META[kind].heading).toMatch(/Types$/);
    }
  });

  it("asSchemaKind rejects non-kinds (documentKinds, junk, nullish) with null", () => {
    for (const notAKind of ["plot_template", "structure_node", "chat", "", "Plot"] as unknown as SchemaKind[]) {
      expect(asSchemaKind(notAKind)).toBeNull();
    }
    expect(asSchemaKind(null)).toBeNull();
    expect(asSchemaKind(undefined)).toBeNull();
  });

  it("asSchemaKind rejects Object.prototype keys — Object.hasOwn, not `in`", () => {
    // `in` would walk the prototype chain and wrongly accept these as kinds.
    for (const protoKey of ["constructor", "toString", "hasOwnProperty", "valueOf", "__proto__", "isPrototypeOf"] as unknown as SchemaKind[]) {
      expect(asSchemaKind(protoKey)).toBeNull();
    }
  });
});

describe("resolveSchemaScope — the Detail Types cascade end-to-end (#729)", () => {
  // A schema that roots plot under an abstract plot:base (the #724 shape), plus a
  // scene:scene so the scene fallback is exercisable.
  const CASCADE_SCHEMA = {
    version: 1,
    entry_types: {
      "scene:scene": { name: "Scene", kind: "scene" },
      "plot:base": { name: "Plot", kind: "plot", abstract: true },
      "plot:template": { name: "Plot template", kind: "plot", parent: "plot:base" },
      "plot:plotline": { name: "Plotline", kind: "plot", parent: "plot:base" },
      "plot:card": { name: "Card", kind: "plot", parent: "plot:base" },
    },
    fields: {},
  } as unknown as MetadataSchema;

  const treeIds = (nodes: NodeTypeTreeNode[]): string[] =>
    nodes.flatMap((node) => [node.id, ...treeIds(node.children)]);

  it("resolves a plot entry type to {kind:plot, heading:'Plot Types', tree of plot types}", () => {
    // This is the whole path that shipped broken: a plot type must yield the plot
    // kind (not scene), the plot heading, AND a tree of plot types — the three
    // coupled together, which SchemaPanes can't be mounted to assert.
    const scope = resolveSchemaScope(CASCADE_SCHEMA, "plot:template");
    expect(scope.kind).toBe("plot");
    expect(scope.heading).toBe("Plot Types");
    // plot:card (S5a, #738) resolves into the Plot tree like every plot type —
    // this is what makes it visible + editable under Detail Types → Plot, the
    // requirement of #738. SchemaPanes is a headless RegionRegistrar (can't be
    // mounted), so this scope test is the render coverage for that surface.
    expect(treeIds(scope.tree)).toEqual(
      expect.arrayContaining(["plot:base", "plot:template", "plot:plotline", "plot:card"]),
    );
    // And NOT the scene tree — the exact collapse the old ternary caused.
    expect(treeIds(scope.tree)).not.toContain("scene:scene");
  });

  it("resolves a scene entry type to the scene scope", () => {
    const scope = resolveSchemaScope(CASCADE_SCHEMA, "scene:scene");
    expect(scope.kind).toBe("scene");
    expect(scope.heading).toBe("Scene Types");
  });

  it("falls back to scene when the entry type is unknown or the schema is null", () => {
    expect(resolveSchemaScope(CASCADE_SCHEMA, "nope:nope").kind).toBe("scene");
    const nullScope = resolveSchemaScope(null, "plot:template");
    expect(nullScope.kind).toBe("scene");
    expect(nullScope.heading).toBe("Scene Types");
    expect(nullScope.tree).toEqual([]);
  });
});

describe("schemaKindForDocumentKind", () => {
  it("resolves plot's per-type documentKinds to the plot schema kind (#729)", () => {
    // The editor opens plot via per-type documentKinds (`plot_template` today;
    // `plot_plotline` / `plot_board` follow in later slices). All are governed by
    // the single `plot` schema tree, so "Edit type…" / Detail Types must map every
    // `plot*` documentKind to "plot" — the prefix match is deliberate so future
    // per-type kinds need no change here.
    expect(schemaKindForDocumentKind("plot_template")).toBe("plot");
    expect(schemaKindForDocumentKind("plot_plotline")).toBe("plot");
    expect(schemaKindForDocumentKind("plot_board")).toBe("plot");
  });

  it("maps structure_node (a scene in the manuscript tree) to scene", () => {
    expect(schemaKindForDocumentKind("structure_node")).toBe("scene");
  });

  it("passes the plain schema kinds through unchanged", () => {
    for (const kind of ["scene", "lore", "research", "prompt", "assistant", "project"] as const) {
      expect(schemaKindForDocumentKind(kind)).toBe(kind);
    }
  });

  it("returns null for DocumentKinds with no schema tree", () => {
    expect(schemaKindForDocumentKind("chat")).toBeNull();
    expect(schemaKindForDocumentKind("snippet")).toBeNull();
    expect(schemaKindForDocumentKind("view")).toBeNull();
  });
});

describe("coerceStringList", () => {
  it("splits a comma string into trimmed, non-empty tokens (no de-dupe)", () => {
    expect(coerceStringList(" a , b ,, A ")).toEqual(["a", "b", "A"]);
  });

  it("coerces an array of items to trimmed strings, dropping empties", () => {
    expect(coerceStringList([" x ", "", 3, "  "])).toEqual(["x", "3"]);
  });

  it("returns an empty list for null / undefined / empty string", () => {
    expect(coerceStringList(null)).toEqual([]);
    expect(coerceStringList(undefined)).toEqual([]);
    expect(coerceStringList("")).toEqual([]);
  });
});

describe("normalizeListFieldValue", () => {
  // #704: the tags SAVE path — not just the render — must de-dupe, so a case
  // duplicate from an importer / hand-edited YAML can't be persisted.
  it("de-dupes a tags value case-insensitively (first spelling wins)", () => {
    expect(normalizeListFieldValue("tags", "Alpha, alpha, beta, BETA")).toEqual(["Alpha", "beta"]);
  });

  it("de-dupes tags whether the value arrives as a string or an array", () => {
    expect(normalizeListFieldValue("tags", ["a", "A", "b"])).toEqual(["a", "b"]);
  });

  // #725: multi_select is a controlled vocabulary — de-dupe CASE-INSENSITIVELY,
  // matching the toggle's case-insensitive option compare, so a case dup can't be
  // persisted while the toggle treats the two as one.
  it("de-dupes multi_select case-insensitively (first spelling wins)", () => {
    expect(normalizeListFieldValue("multi_select", "Draft, draft, Final")).toEqual(["Draft", "Final"]);
    expect(normalizeListFieldValue("multi_select", ["a", "a", "A", "b"])).toEqual(["a", "b"]);
  });

  // #725: entity_ref_list items are identifiers — de-dupe CASE-SENSITIVELY, so
  // exact dups collapse but `Alpha`/`alpha` stay distinct refs.
  it("de-dupes entity_ref_list case-sensitively (exact dups only)", () => {
    expect(normalizeListFieldValue("entity_ref_list", ["x", "x", "y"])).toEqual(["x", "y"]);
    expect(normalizeListFieldValue("entity_ref_list", "Alpha, alpha, Alpha")).toEqual(["Alpha", "alpha"]);
  });

  // A non-set field type is not list-shaped and passes through untouched.
  it("passes an unknown field type through without de-duping", () => {
    expect(normalizeListFieldValue("text", "a, a, b")).toEqual(["a", "a", "b"]);
  });
});

describe("kindEntryTypeOptions", () => {
  it("excludes abstract types by default and filters to the kind", () => {
    expect(kindEntryTypeOptions(SCHEMA, "lore")).toEqual([
      { fqn: "lore:character", name: "Character" },
      { fqn: "lore:place", name: "Place" },
    ]);
  });

  it("includes abstract family roots when asked (descendants_of)", () => {
    expect(kindEntryTypeOptions(SCHEMA, "lore", true)).toEqual([
      { fqn: "lore:base", name: "Lore" },
      { fqn: "lore:character", name: "Character" },
      { fqn: "lore:place", name: "Place" },
    ]);
  });

  it("is empty for an absent schema or a kind with no types", () => {
    expect(kindEntryTypeOptions(null, "lore")).toEqual([]);
    expect(kindEntryTypeOptions(SCHEMA, "prompt")).toEqual([]);
  });
});

describe("nestingLocalPrefix (#600 — roll a sub-type id nested under its parent)", () => {
  const PROMPT_SCHEMA = {
    version: 1,
    entry_types: {
      "prompt:base": { name: "Prompt", kind: "prompt", abstract: true },
      "prompt:revise": { name: "Revise", kind: "prompt", parent: "prompt:base", abstract: true },
      "prompt:revise:scene": { name: "Revise Scene", kind: "prompt", parent: "prompt:revise" },
    },
    fields: {},
  } as unknown as MetadataSchema;

  it("nests under a concrete parent's local key", () => {
    expect(nestingLocalPrefix(PROMPT_SCHEMA, "prompt", "prompt:revise")).toBe("revise");
  });

  it("keeps the parent's full nested local path for a grandchild", () => {
    expect(nestingLocalPrefix(PROMPT_SCHEMA, "prompt", "prompt:revise:scene")).toBe("revise:scene");
  });

  it("stays flat under the kind's abstract root or no parent", () => {
    expect(nestingLocalPrefix(PROMPT_SCHEMA, "prompt", "prompt:base")).toBe("");
    expect(nestingLocalPrefix(PROMPT_SCHEMA, "prompt", null)).toBe("");
    expect(nestingLocalPrefix(PROMPT_SCHEMA, "prompt", "")).toBe("");
  });

  it("does not nest under a parent of a different kind", () => {
    expect(nestingLocalPrefix(PROMPT_SCHEMA, "prompt", "lore:character")).toBe("");
  });
});

describe("kindEntryTypeFqns (delegates to the concrete roster)", () => {
  it("returns concrete FQNs only", () => {
    expect(kindEntryTypeFqns(SCHEMA, "lore")).toEqual(["lore:character", "lore:place"]);
  });
});

describe("isMetadataValuePresent", () => {
  it("treats undefined / null / empty string / empty list as unset", () => {
    expect(isMetadataValuePresent(undefined)).toBe(false);
    expect(isMetadataValuePresent(null)).toBe(false);
    expect(isMetadataValuePresent("")).toBe(false);
    expect(isMetadataValuePresent([])).toBe(false);
  });

  it("treats false and 0 as present — the sharp boolean case (#522)", () => {
    // A boolean field set to false is SET, not unset; a two-state toggle would
    // otherwise render it identically to an untouched (absent) field.
    expect(isMetadataValuePresent(false)).toBe(true);
    expect(isMetadataValuePresent(0)).toBe(true);
  });

  it("treats non-empty scalars and lists as present", () => {
    expect(isMetadataValuePresent(true)).toBe(true);
    expect(isMetadataValuePresent("first")).toBe(true);
    expect(isMetadataValuePresent(42)).toBe(true);
    expect(isMetadataValuePresent(["a"])).toBe(true);
  });
});
