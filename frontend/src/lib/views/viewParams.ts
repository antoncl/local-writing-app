// The runtime half of parameterized views (#184 Phase 1a, ADR-0032): turn a
// stored `ViewSpec.params` list into the controls a pane's parameter strip
// renders, and fold the strip's values into an `EvalBindings` the evaluator
// consumes. Pure and framework-free (no store/component imports beyond types),
// so it is unit-testable and portable to whatever hosts the strip — the Lore
// pane today, the #182 canonical wrapper when it lands.
//
// Type derivation (§14.1): a param stores NO type. Its control's field def is
// recomputed from the field(s) whose Filter slot references it via `{var: name}`
// — the intersection rule (ADR-0031 §F). This cut takes the first referencing
// slot's field (the single-slot common case); the intersection refinement and a
// cross-slot-mismatch warning are deferred with the designer authoring (1b).

import type { MetadataFieldDefinition, MetadataSchema, ViewExpr, ViewParam, ViewSpec } from "@/lib/types";
import { SELF_VAR, type EvalBindings } from "@/lib/views/evaluateView";
import { walkViewExpr } from "@/lib/views/walkViewExpr";

// A resolved strip control: the declared formal + the field its editor derives
// from. `fieldKey` is "" when no referencing slot was found (→ a text fallback).
export type ParamControl = {
  name: string;
  label: string;
  field: MetadataFieldDefinition;
  fieldKey: string;
};

// A minimal text field for a formal no Filter slot references yet (or whose
// referencing field is absent from the schema): the strip still shows a control.
function textFallback(name: string): MetadataFieldDefinition {
  return { name, type: "text", options: [] };
}

// A promoted param always fills an overlap/disjoint predicate's `value` operand
// (the only value-bearing ops — `set`/`unset` carry none), which is compared as a
// SET. So the strip control must be MULTI-valued regardless of the field's own
// cardinality: a single `pov` (entity_ref) filters `pov ∈ {picked}`, a single
// `status` (select) filters `status ∈ {picked}` (the "this OR that" query). The
// binding is already a `string[]` and the evaluator set-coerces (viewParams
// `buildBindings`); this only widens the editor. Field types that are already
// multi (entity_ref_list / multi_select / tags) or have no set widget pass through.
// Exported so the designer's inline value editor (ViewFlowNode) widens the same way
// — one place for the "overlap operand is a set" rule.
export function toMultiValued(field: MetadataFieldDefinition): MetadataFieldDefinition {
  if (field.type === "entity_ref") return { ...field, type: "entity_ref_list" };
  // `multi_select` needs options to render (FieldValueEditor gates its chips on
  // `options.length > 0`); an options-less select would fall through to the raw
  // text input, so leave it a single `select`.
  if (field.type === "select" && field.options.length > 0) return { ...field, type: "multi_select" };
  return field;
}

function isVarOperand(v: unknown): v is { var: string } {
  return typeof v === "object" && v !== null && typeof (v as { var?: unknown }).var === "string";
}

// Map each formal name → the field keys whose predicate operand is `{var: name}`.
// Only predicate operands need a control: `$self` is surface-supplied and a
// `field_of` `of`-var is a wired source, neither a user-facing formal. Traversal
// is the shared `walkViewExpr` (#275) — so a promoted formal buried anywhere,
// including inside an orphans-only Nest, is found.
function collectReferencingFieldKeys(spec: ViewSpec): Map<string, string[]> {
  const out = new Map<string, string[]>();
  const add = (name: string, key: string): void => {
    const list = out.get(name);
    if (list) {
      if (!list.includes(key)) list.push(key);
    } else {
      out.set(name, [key]);
    }
  };
  const visit = (e: ViewExpr): void => {
    if (e.field) {
      const v = e.field.value;
      if (isVarOperand(v) && v.var !== SELF_VAR) add(v.var, e.field.key);
    }
  };
  walkViewExpr(spec.expr, visit);
  spec.groups?.forEach((g) => walkViewExpr(g.expr, visit));
  return out;
}

// Resolve the strip controls for a spec's declared formals, in declaration order.
export function resolveParamControls(
  spec: ViewSpec,
  schema: MetadataSchema | null | undefined,
): ParamControl[] {
  const params = spec.params ?? [];
  if (params.length === 0) return [];
  const keysByName = collectReferencingFieldKeys(spec);
  return params.map((p) => {
    const fieldKey = keysByName.get(p.name)?.[0] ?? "";
    const resolved = (fieldKey ? schema?.fields?.[fieldKey] : null) ?? textFallback(p.label || p.name);
    return { name: p.name, label: p.label || p.name, field: toMultiValued(resolved), fieldKey };
  });
}

// The effective operand for a formal: an ephemeral pane override wins over the
// authored default (ADR-0032 §C). Coerced to a string list (the id/value-set
// shape a binding carries).
export function effectiveParamValue(
  param: ViewParam,
  overrides: Record<string, unknown>,
): string[] {
  const raw = param.name in overrides ? overrides[param.name] : param.default;
  return toStringList(raw);
}

// Fold declared formals + overrides into an `EvalBindings`. A formal whose
// effective value is empty is OMITTED — so its predicate stays inactive (the
// input passes through), a search-box's empty state (ADR-0031 §B). `$self` is
// never here (surface-supplied).
export function buildBindings(
  params: ViewParam[] | null | undefined,
  overrides: Record<string, unknown>,
): EvalBindings {
  const bindings: EvalBindings = {};
  for (const p of params ?? []) {
    const value = effectiveParamValue(p, overrides);
    if (value.length > 0) bindings[p.name] = value;
  }
  return bindings;
}

function toStringList(v: unknown): string[] {
  if (v == null) return [];
  if (Array.isArray(v)) return v.map((x) => String(x).trim()).filter(Boolean);
  if (typeof v === "string") return v.split(",").map((s) => s.trim()).filter(Boolean);
  return [String(v).trim()].filter(Boolean);
}
