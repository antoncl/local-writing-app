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
    expect(controls.map((c) => [c.name, c.field.type, c.fieldKey])).toEqual([
      ["POV", "entity_ref", "pov_ref"],
      ["Status", "select", "status"],
    ]);
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

  it("$self operands are NOT formals (surface-supplied, no control)", () => {
    const spec: ViewSpec = {
      kind: "scene",
      expr: { field: { key: "pov_ref", op: "overlap", value: { var: "$self" } } },
      params: [],
    };
    expect(resolveParamControls(spec, SCHEMA)).toEqual([]);
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
