import { describe, expect, it } from "vitest";
import type { MetadataSchema, ViewSpec } from "@/lib/types";
import { buildBindings, effectiveParamValue, resolveParamControls } from "@/lib/views/viewParams";

const SCHEMA = {
  version: 1,
  entry_types: {},
  fields: {
    pov_ref: { name: "POV", type: "entity_ref", options: [] },
    status: { name: "Status", type: "select", options: [{ value: "draft" }, { value: "revised" }] },
  },
} as unknown as MetadataSchema;

describe("resolveParamControls (type derived from the referencing Filter slot)", () => {
  it("derives each control's field def from the field its {var} operand sits on", () => {
    const spec: ViewSpec = {
      kind: "scene",
      expr: {
        intersect: [
          { field: { key: "pov_ref", op: "overlap", value: { var: "POV" } } },
          { field: { key: "status", op: "overlap", value: { var: "Status" } } },
        ],
      },
      params: [
        { name: "POV", label: "Point of view", default: null },
        { name: "Status", label: "Status", default: ["draft"] },
      ],
    };
    const controls = resolveParamControls(spec, SCHEMA);
    // A promoted param fills an overlap/disjoint operand — a SET — so the control
    // WIDENS to the field's multi variant (entity_ref→entity_ref_list,
    // select→multi_select) so you can seed `pov ∈ {A,B}` / `status ∈ {draft,revised}`.
    // The fieldKey stays the original key.
    expect(controls.map((c) => [c.name, c.field.type, c.fieldKey])).toEqual([
      ["POV", "entity_ref_list", "pov_ref"],
      ["Status", "multi_select", "status"],
    ]);
  });

  it("already-multi and non-set fields pass through un-widened", () => {
    const schema = {
      version: 1,
      entry_types: {},
      fields: {
        allies: { name: "Allies", type: "entity_ref_list", options: [] },
        note: { name: "Note", type: "text", options: [] },
        // a select with NO options: must stay `select`, not widen to multi_select
        // (which FieldValueEditor can't render → falls through to a text box).
        bare: { name: "Bare", type: "select", options: [] },
      },
    } as unknown as MetadataSchema;
    const spec: ViewSpec = {
      kind: "lore",
      expr: {
        intersect: [
          { field: { key: "allies", op: "overlap", value: { var: "Allies" } } },
          { field: { key: "note", op: "overlap", value: { var: "Note" } } },
          { field: { key: "bare", op: "overlap", value: { var: "Bare" } } },
        ],
      },
      params: [
        { name: "Allies", label: "Allies", default: null },
        { name: "Note", label: "Note", default: null },
        { name: "Bare", label: "Bare", default: null },
      ],
    };
    expect(resolveParamControls(spec, schema).map((c) => c.field.type)).toEqual(["entity_ref_list", "text", "select"]);
  });

  it("finds operands nested in groups + set algebra", () => {
    const spec: ViewSpec = {
      kind: "scene",
      groups: [{ name: "G", expr: { difference: { keep: { type: "scene:scene" }, remove: { field: { key: "status", op: "overlap", value: { var: "Status" } } } } } }],
      params: [{ name: "Status", label: "Status", default: null }],
    };
    expect(resolveParamControls(spec, SCHEMA)[0].fieldKey).toBe("status");
  });

  it("unreferenced / schema-absent formal → a text fallback control", () => {
    const spec: ViewSpec = { kind: "scene", expr: { type: "scene:scene" }, params: [{ name: "Loose", label: "Loose" }] };
    const [c] = resolveParamControls(spec, SCHEMA);
    expect([c.field.type, c.fieldKey]).toEqual(["text", ""]);
  });

  it("a `type`-referenced param → an entry_type select (widened to multi_select), #293", () => {
    const schema = {
      version: 1,
      entry_types: {
        "lore:character": { name: "Character", kind: "lore" },
        "lore:place": { name: "Place", kind: "lore" },
        "lore:base": { name: "Base", kind: "lore", abstract: true },
        "scene:scene": { name: "Scene", kind: "scene" },
      },
      fields: {},
    } as unknown as MetadataSchema;
    const spec: ViewSpec = {
      kind: "lore",
      expr: { filter: { of: { descendants_of: "lore:base" }, pred: { type: { var: "Kind" } } } },
      params: [{ name: "Kind", label: "Entry type", default: null }],
    };
    const [c] = resolveParamControls(spec, schema);
    // Non-abstract types of the view's kind only — `lore:base` (abstract) and
    // `scene:scene` (other kind) are excluded — value=FQN, label=display name.
    expect(c.field.type).toBe("multi_select");
    expect(c.field.options).toEqual([
      { value: "lore:character", label: "Character" },
      { value: "lore:place", label: "Place" },
    ]);
    expect(c.fieldKey).toBe("entry_type");
  });

  it("a `descendants_of`-referenced param INCLUDES abstract family roots (unlike `type`), #293", () => {
    const schema = {
      version: 1,
      entry_types: {
        "lore:base": { name: "Lore", kind: "lore", abstract: true },
        "lore:character": { name: "Character", kind: "lore" },
      },
      fields: {},
    } as unknown as MetadataSchema;
    const spec: ViewSpec = {
      kind: "lore",
      expr: { filter: { of: { descendants_of: "lore:base" }, pred: { descendants_of: { var: "Family" } } } },
      params: [{ name: "Family", label: "Family", default: null }],
    };
    const [c] = resolveParamControls(spec, schema);
    // `descendants_of` expands a family, so the abstract root `lore:base` IS an
    // offerable value — the exact-match `type` picker (above) excludes it.
    expect(c.field.type).toBe("multi_select");
    expect(c.field.options).toEqual([
      { value: "lore:base", label: "Lore" },
      { value: "lore:character", label: "Character" },
    ]);
    expect(c.fieldKey).toBe("entry_type");
  });

  it("a `type` param with no offerable entry_types → a usable text fallback, not a dead select, #293", () => {
    // schema=null (not yet loaded) ⇒ empty roster ⇒ an empty <select> would be
    // un-pickable, so the control degrades to a text box (type an FQN).
    const spec: ViewSpec = {
      kind: "lore",
      expr: { filter: { of: { descendants_of: "lore:base" }, pred: { type: { var: "Kind" } } } },
      params: [{ name: "Kind", label: "Kind", default: null }],
    };
    const [c] = resolveParamControls(spec, null);
    expect(c.field.type).toBe("text");
  });

  it("a `tagged`-referenced param → a tags control (retired for authoring, hand-written specs), #293", () => {
    const spec: ViewSpec = {
      kind: "lore",
      expr: { filter: { of: { descendants_of: "lore:base" }, pred: { tagged: { var: "Tag" } } } },
      params: [{ name: "Tag", label: "Tag", default: null }],
    };
    const [c] = resolveParamControls(spec, SCHEMA);
    expect([c.field.type, c.fieldKey]).toEqual(["tags", "tags"]);
  });

  it("no params ⇒ no controls (degenerate closed view)", () => {
    expect(resolveParamControls({ kind: "lore", expr: null }, SCHEMA)).toEqual([]);
  });
});

describe("buildBindings (default seeds, override wins, empty ⇒ inactive)", () => {
  const params = [
    { name: "POV", label: "POV", default: null },
    { name: "Status", label: "Status", default: ["draft", "revised"] },
  ];

  it("seeds from authored defaults; omits empty (inactive) formals", () => {
    const bindings = buildBindings(params, {});
    expect(bindings).not.toHaveProperty("POV"); // null default ⇒ omitted ⇒ inactive
    expect(bindings.Status).toEqual(["draft", "revised"]);
  });

  it("an ephemeral override wins over the default", () => {
    const bindings = buildBindings(params, { POV: ["char-bob"], Status: "draft" });
    expect(bindings.POV).toEqual(["char-bob"]);
    expect(bindings.Status).toEqual(["draft"]);
  });

  it("clearing an override back to empty drops the formal (re-inactive)", () => {
    expect(buildBindings(params, { Status: [] })).not.toHaveProperty("Status");
  });

  it("effectiveParamValue coerces scalars and CSV to a string list", () => {
    expect(effectiveParamValue({ name: "x", default: "a, b" }, {})).toEqual(["a", "b"]);
    expect(effectiveParamValue({ name: "x", default: 7 }, {})).toEqual(["7"]);
    expect(effectiveParamValue({ name: "x", default: null }, {})).toEqual([]);
  });
});
