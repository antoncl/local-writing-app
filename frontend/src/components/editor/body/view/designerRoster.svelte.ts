// The view designer's schema-derived field roster + authoring-time type
// inference, extracted from ViewBodyView (size cap, #2528). Reads only the
// metadata schema, the anchor kind and the live canvas arrays (through getters,
// so every derived tracks the owner's state); owns no markup.
import type { Edge, Node } from "@xyflow/svelte";
import {
  effectiveFieldLabel,
  effectiveFieldHidden,
  kindRootEntryTypeId,
  kindEntryTypeFqns,
  kindEntryTypeOptions,
  descendantTypeFqns,
  intersectFieldKeysOverTypes,
} from "@/lib/utils/schemaTypeHelpers";
import { pickerMembership } from "@/lib/utils/pickerSources";
import { liftFieldByKey, liftFieldsForKind } from "@/lib/views/computedFields";
import { inferInputTypes, inputKinds, type InputTypeSet, type TypeResolvers } from "@/lib/views/viewGraph";
import type { MetadataFieldDefinition, MetadataSchema } from "@/lib/types";
import type { EntryTypeOption, FieldOption, RosterWarning } from "./designerContext";
import { buildInferenceGraph, type FlowData } from "./hydrateView";

// Structural containment ref (ADR-0029 §D `computed` category / #217): scenes
// and research notes carry a `parent` metadata ref stamped from the structure
// tree (`structureNodes.ts`), which drives `defaultView()`'s containment Nest.
// It's not a schema-declared field, so it's absent from the entry_type rosters
// — leaving every field picker (filter predicate, Nest link, field_of, group_by)
// unable to show, select, or RESTORE it (#251). Inject it as a first-class
// computed reference field so all those pickers offer it uniformly. `entity_ref`
// + non-intrinsic category = joinable AND groupable, matching how the evaluator
// follows it (`match.field: parent`, by ref). `children` is deferred to #217: no
// node stamps it, so the evaluator has no inverse index to resolve it yet.
const STRUCTURAL_KINDS = new Set(["manuscript", "research"]);

// The structural `parent` ref as a computed reference field, scoped to kind `k`
// so its value widget (op overlap/disjoint → ReferencePicker) offers that kind's
// nodes — without a `picker_config` the picker falls back to the `lore` roster.
function parentFieldDef(k: string): MetadataFieldDefinition {
  return { name: "Parent", type: "entity_ref", options: [], category: "computed", picker_config: { sources: [{ kind: k }] } };
}

export class DesignerRoster {
  #getSchema: () => MetadataSchema | null;
  #getKind: () => string;
  #getNodes: () => Node<FlowData>[];
  #getEdges: () => Edge[];

  // ---- schema-derived leaf-config options for the current kind ----
  entryTypes: EntryTypeOption[];
  // The `descendants_of` roster includes abstract family roots (#295); `type` and
  // `field → entry_type` use the concrete-only `entryTypes` above.
  entryTypesWithAbstract: EntryTypeOption[];
  // The anchor-kind roster (see `buildFieldOptions`).
  fields: FieldOption[];
  // Rebuilt once per graph mutation (a $derived), not per picker call —
  // `fieldsFor` runs per node per render, so a per-call rebuild would be
  // O(N²) over the node count.
  inferenceGraph: ReturnType<typeof buildInferenceGraph>;

  // The deriveds are assigned here (not as field initialisers) so they run after
  // the getters above are set; each reads its getters INSIDE the derived so it
  // tracks the owner's live state.
  constructor(deps: {
    getSchema: () => MetadataSchema | null;
    getKind: () => string;
    getNodes: () => Node<FlowData>[];
    getEdges: () => Edge[];
  }) {
    this.#getSchema = deps.getSchema;
    this.#getKind = deps.getKind;
    this.#getNodes = deps.getNodes;
    this.#getEdges = deps.getEdges;
    this.entryTypes = $derived(kindEntryTypeOptions(this.#getSchema(), this.#getKind()));
    this.entryTypesWithAbstract = $derived(kindEntryTypeOptions(this.#getSchema(), this.#getKind(), true));
    this.fields = $derived(this.buildFieldOptions(this.#getKind()));
    this.inferenceGraph = $derived.by(() => buildInferenceGraph(this.#getNodes(), this.#getEdges()));
  }

  // Shared roster builder: field keys → sorted FieldOptions, resolving per-type
  // label/hidden against `anchor` — the kind ROOT for a single kind (ADR-0029 §F:
  // the built-in lore `title → "Name"` relabel sits on `lore:base` and reaches the
  // picker; a leaf-only override deliberately does not), or the bare def (null) for
  // a cross-kind set with no single root. Intrinsics (id/title/entry_type, #116)
  // are regular injected fields, pinned first; `hidden` ones (id) are skipped.
  fieldOptionsFromKeys(keys: Iterable<string>, anchor: string | null): FieldOption[] {
    const schema = this.#getSchema();
    const out: FieldOption[] = [];
    for (const k of keys) {
      const def = schema?.fields?.[k];
      if (!def || effectiveFieldHidden(schema, anchor, k)) continue;
      out.push({ key: k, name: effectiveFieldLabel(schema, anchor, k), def });
    }
    out.sort((a, b) => {
      const ai = a.def.category === "intrinsic";
      const bi = b.def.category === "intrinsic";
      if (ai !== bi) return ai ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    return out;
  }

  // The computed field options for a set of kinds — fields a kind's universe carries
  // in `metadata` but the schema never declares, so they have no entry_type
  // membership to intersect over and are PREPENDED to a roster rather than merged
  // into the schema-key set. Two sources: the structural `parent` ref (when any kind
  // is a tree kind, kind-scoped picker) and the lift-synthesized fields registered
  // in `computedFields` (`seed_disposition` on chats, #960; prompts' `disposition`
  // graduated to a real schema-declared computed field in #1684, so it arrives
  // through the ordinary schema roster now, not here). A user-declared metadata
  // field with the same key (rare) takes precedence —
  // the real field is already in the roster, so skip the synthetic to avoid a
  // duplicate option (`computedFieldByKey` likewise resolves the schema field first).
  computedFieldOptions(kinds: Iterable<string>): FieldOption[] {
    const schema = this.#getSchema();
    const out: FieldOption[] = [];
    const seen = new Set<string>();
    // #1928: `layer` is UNIVERSAL — not tied to any kind or entry_type (it's the
    // node's own resolved inheritance layer) — so it's added once here rather
    // than per-kind, straight from the resolved schema (single-sourcing its
    // label/options from the backend, like any other computed select). Not
    // tracked in `seen`: nothing below can re-add it (a lift field keyed `layer`
    // is already skipped by the `schema?.fields?.[cf.key]` guard in the loop).
    if (schema?.fields?.layer) {
      out.push({ key: "layer", name: schema.fields.layer.name, def: schema.fields.layer });
    }
    for (const k of kinds) {
      if (!seen.has("parent") && !schema?.fields?.parent && STRUCTURAL_KINDS.has(k)) {
        out.push({ key: "parent", name: "Parent", def: parentFieldDef(k) });
        seen.add("parent");
      }
      for (const cf of liftFieldsForKind(k)) {
        if (seen.has(cf.key) || schema?.fields?.[cf.key]) continue;
        out.push({ key: cf.key, name: cf.def.name, def: cf.def });
        seen.add(cf.key);
      }
    }
    return out;
  }

  // The descriptor for a computed field key on a kind (the `fieldByKey` counterpart
  // of `computedFieldOptions`): structural `parent` or a registered lift field.
  computedFieldByKey(k: string, key: string): MetadataFieldDefinition | null {
    const schema = this.#getSchema();
    if (key === "layer" && schema?.fields?.layer) return schema.fields.layer;
    if (key === "parent" && STRUCTURAL_KINDS.has(k)) return parentFieldDef(k);
    return liftFieldByKey(k, key);
  }

  // A field's definition for the anchor kind: the schema field, else a computed one.
  fieldByKey(key: string): MetadataFieldDefinition | null {
    return this.#getSchema()?.fields?.[key] ?? this.computedFieldByKey(this.#getKind(), key);
  }

  // The anchor-kind roster (union of the kind's fields over its entry_types) — the
  // fallback when a node's input type is indeterminate. Per-node rosters come from
  // `fieldsFor` via §F inference below.
  buildFieldOptions(forKind: string): FieldOption[] {
    const schema = this.#getSchema();
    const keys = new Set<string>();
    for (const [, def] of Object.entries(schema?.entry_types ?? {})) {
      if (def.kind !== forKind) continue;
      for (const fk of def.fields ?? []) keys.add(fk);
    }
    return [...this.computedFieldOptions([forKind]), ...this.fieldOptionsFromKeys(keys, kindRootEntryTypeId(schema, forKind))];
  }

  // Authoring-time TYPE inference (ADR-0031 §F): the entry_type-set of a node's
  // INPUT set, driving which field roster AND tag roster its picker offers.
  typeResolvers: TypeResolvers = {
    fieldDef: (key) => this.#getSchema()?.fields?.[key] ?? null,
    // A ref field's target as a type-set: kind → its entry_type FQNs (empty →
    // whole kind, no entry_type constraint). Multi-kind refs are kept, not nulled
    // — the roster intersects across them (§14.3).
    refTargetTypes: (fieldKey) => {
      const def = this.#getSchema()?.fields?.[fieldKey];
      if (!def) return null;
      const { kinds, entryTypes } = pickerMembership(def.picker_config);
      if (kinds.length === 0) return null;
      return new Map(kinds.map((k) => [k, entryTypes[k]?.length ? new Set(entryTypes[k]) : null]));
    },
    descendantsOf: (fqn) => descendantTypeFqns(this.#getSchema(), fqn),
    kindOfType: (fqn) => this.#getSchema()?.entry_types?.[fqn]?.kind ?? fqn.split(":")[0] ?? null,
  };

  inputTypesForNode(nodeId: string): InputTypeSet | null {
    return inferInputTypes(this.inferenceGraph.byId, this.inferenceGraph.edges, nodeId, this.#getKind(), this.typeResolvers);
  }

  // Expand an inferred input type-set to the concrete entry_type FQNs it can hold
  // (a `null` per-kind constraint → every concrete type of that kind).
  concreteTypesOf(ts: InputTypeSet): string[] {
    const schema = this.#getSchema();
    const out: string[] = [];
    for (const [k, set] of ts) out.push(...(set ? [...set] : kindEntryTypeFqns(schema, k)));
    return out;
  }

  fieldsFor = (nodeId: string): FieldOption[] => {
    const schema = this.#getSchema();
    const ts = this.inputTypesForNode(nodeId);
    if (!ts) return this.fields; // indeterminate → anchor roster
    const fqns = this.concreteTypesOf(ts);
    // Determinate but provably empty (e.g. an intersect of disjoint types) — the
    // set can hold no members, so only the always-present intrinsics apply.
    if (fqns.length === 0) return this.fields.filter((o) => o.def.category === "intrinsic");
    // §F: the fields present on EVERY member — a group-aware set-intersection over
    // the input's concrete types (vertical inheritance AND shared field-groups). A
    // cross-kind set has no single root → resolve labels against the bare def. The
    // computed fields (structural `parent`, and the lift-synthesized
    // seed_disposition) aren't entry_type members, so they survive the intersection
    // only by being prepended here — offered whenever their kind is in the input set
    // (the indeterminate branch above inherits them via `fields`).
    const anchor = ts.size === 1 ? kindRootEntryTypeId(schema, [...ts.keys()][0]) : null;
    return [
      ...this.computedFieldOptions(ts.keys()),
      ...this.fieldOptionsFromKeys(intersectFieldKeysOverTypes(schema, fqns), anchor),
    ];
  };

  // The authoring warning ADR-0031 §F asks for (Slice B, #215): when a picker
  // node's inferred INPUT set is cross-kind, its roster is a degraded intersection,
  // not the precise single-kind roster. Cross-kind ⇔ the type-set spans a number of
  // kinds OTHER than exactly one:
  //  - size > 1 — a genuine multi-kind set (union of kinds, cross-kind ref, Nest);
  //  - size 0 (a determinate, NON-null empty Map) — a cross-kind INTERSECT that
  //    collapsed to nothing (`combineTypeSets` drops every kind when the branches
  //    share none, e.g. `scenes ∩ characters`), the thinnest roster of all and
  //    exactly the "nothing in common → down to intrinsics" case §F names.
  // Silent (null) otherwise: `ts === null` (indeterminate → anchor fallback), and
  // size 1 — a single kind, INCLUDING a same-kind empty intersect (`{scene:∅}`),
  // which is a distinct impossible-filter diagnostic out of §F's cross-kind scope.
  // `thin` reuses `fieldsFor` (the roster the picker actually shows), so for a
  // cross-kind node the note always agrees with the dropdown.
  rosterWarningFor = (nodeId: string): RosterWarning | null => {
    const ts = this.inputTypesForNode(nodeId);
    if (ts === null || ts.size === 1) return null;
    const kinds = inputKinds(ts).sort();
    const thin = !this.fieldsFor(nodeId).some((o) => o.def.category !== "intrinsic");
    return { kinds, thin };
  };
}
