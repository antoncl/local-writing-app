// The runtime half of parameterized views (#184 Phase 1a, ADR-0032): turn a
// stored `ViewSpec.params` list into the controls a pane's parameter strip
// renders, and fold the strip's values into an `EvalBindings` the evaluator
// consumes. Pure and framework-free (no store/component imports beyond types),
// so it is unit-testable and portable to whatever hosts the strip — the Lore
// pane today, the #182 canonical wrapper when it lands.
//
// Type derivation (§14.1): a param stores NO type. Its control's field def is
// recomputed from the slot(s) that reference it via `{var: name}`. A `field`
// predicate operand derives from the schema field it sits on (the intersection
// rule, ADR-0031 §F). A leaf predicate (`type` / `descendants_of` / `tagged`,
// #222) has no schema field, so its control is SYNTHESIZED — an entry_type
// select for `type`/`descendants_of`, a tags picker for `tagged` — mirroring the
// designer's own inline editors. This cut takes the first referencing slot (the
// single-slot common case); the intersection refinement and a cross-slot-mismatch
// warning are deferred with the designer authoring (1b).

import type { MetadataFieldDefinition, MetadataSchema, SelectOption, ViewExpr, ViewLeafValue, ViewParam, ViewSpec } from "@/lib/types";
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

// A var promoted into a `type`/`descendants_of` leaf compares entry_type FQNs, so
// synthesize a `select` over the schema's entry_types — the same roster the
// designer offers (ViewBodyView `entryTypeOptions`): non-abstract types of the
// view's kind, FQN value + display-name label. `toMultiValued` then widens it to a
// multi_select, since a bound leaf operand matches ANY of a set (#222).
function entryTypeField(name: string, kind: string, schema: MetadataSchema | null | undefined): MetadataFieldDefinition {
  const options: SelectOption[] = Object.entries(schema?.entry_types ?? {})
    .filter(([, def]) => def.kind === kind && !def.abstract)
    .map(([fqn, def]) => ({ value: fqn, label: def.name }));
  return { name, type: "select", options };
}

// A var promoted into a `tagged` leaf compares tags → a tags picker (already
// multi-valued, so `toMultiValued` passes it through). `tagged` is retired as a
// designer-authorable predicate (ViewFlowNode), reachable only via a hand-written
// spec, but the derivation blind spot was the same, so it's covered here.
function taggedField(name: string): MetadataFieldDefinition {
  return { name, type: "tags", options: [] };
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

// A var reference discovered in the spec. A `field`-predicate operand derives its
// control from the schema field it sits on; a leaf predicate has no schema field,
// so its control is synthesized — `entry_type` covers both `type` and
// `descendants_of` (both compare entry_type FQNs), `tagged` compares tags.
type ParamRef = { kind: "field"; key: string } | { kind: "entry_type" } | { kind: "tagged" };

// Map each formal name → the slot references whose operand is `{var: name}`.
// Only predicate operands need a control: `$self` is surface-supplied and a
// `field_of` `of`-var is a wired source, neither a user-facing formal. Traversal
// is the shared `walkViewExpr` (#275) — so a promoted formal buried anywhere,
// including inside an orphans-only Nest, is found. The leaf slots (`type` /
// `descendants_of` / `tagged`) carry a `{var}` just like a field value does (#222),
// so all four are inspected — walking only `field.value` was the #293 blind spot.
function collectParamRefs(spec: ViewSpec): Map<string, ParamRef[]> {
  const out = new Map<string, ParamRef[]>();
  const add = (name: string, ref: ParamRef): void => {
    const list = out.get(name);
    if (list) list.push(ref);
    else out.set(name, [ref]);
  };
  const leafVar = (v: ViewLeafValue | undefined): string | null =>
    isVarOperand(v) && v.var !== SELF_VAR ? v.var : null;
  const visit = (e: ViewExpr): void => {
    if (e.field && isVarOperand(e.field.value) && e.field.value.var !== SELF_VAR) add(e.field.value.var, { kind: "field", key: e.field.key });
    const t = leafVar(e.type) ?? leafVar(e.descendants_of);
    if (t) add(t, { kind: "entry_type" });
    const g = leafVar(e.tagged);
    if (g) add(g, { kind: "tagged" });
  };
  walkViewExpr(spec.expr, visit);
  spec.groups?.forEach((g) => walkViewExpr(g.expr, visit));
  return out;
}

// The unwidened control field + informational `fieldKey` for a single reference.
// A field ref keeps its schema key (even when the schema lacks it → a text
// fallback still labelled by the key); a synthesized leaf control reports the
// intrinsic key it stands in for.
function controlFieldFor(
  ref: ParamRef | undefined,
  label: string,
  kind: string,
  schema: MetadataSchema | null | undefined,
): { field: MetadataFieldDefinition; fieldKey: string } {
  if (ref?.kind === "field") return { field: schema?.fields?.[ref.key] ?? textFallback(label), fieldKey: ref.key };
  if (ref?.kind === "entry_type") return { field: entryTypeField(label, kind, schema), fieldKey: "entry_type" };
  if (ref?.kind === "tagged") return { field: taggedField(label), fieldKey: "tags" };
  return { field: textFallback(label), fieldKey: "" };
}

// Resolve the strip controls for a spec's declared formals, in declaration order.
export function resolveParamControls(
  spec: ViewSpec,
  schema: MetadataSchema | null | undefined,
): ParamControl[] {
  const params = spec.params ?? [];
  if (params.length === 0) return [];
  const refsByName = collectParamRefs(spec);
  return params.map((p) => {
    const label = p.label || p.name;
    const { field, fieldKey } = controlFieldFor(refsByName.get(p.name)?.[0], label, spec.kind, schema);
    return { name: p.name, label, field: toMultiValued(field), fieldKey };
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
