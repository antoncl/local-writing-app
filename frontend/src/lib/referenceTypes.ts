// Reference / backlink wire types. Extracted from types.ts to keep that
// barrel under the file-size cap; re-exported from `@/lib/types` so it stays
// the single import surface.

export type ReferenceCandidate = {
  id: string;
  title: string;
  kind: string;
  entry_type: string;
  summary: string;
  found: boolean;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type ReferenceCandidatesResponse = {
  candidates: ReferenceCandidate[];
};

export type ReferenceResolveResponse = {
  candidates: ReferenceCandidate[];
};

export type Backlink = {
  id: string;
  title: string;
  kind: string;
  entry_type: string;
  field_id: string;
  field_name: string;
};

// What a navigate affordance (backlink row, reference pill) hands the shell to open a
// node: id + kind, plus the entry type because the plot family dispatches on it (#1920).
export type NavigateTarget = { id: string; kind: string; entryType?: string };

// One field-qualified forward edge (ADR-0089 §9): `src` references `dst`
// through `field_id`. Additive alongside `refs` — the keyed-referrer index
// behind the delete-orphan warning needs to know which field an edge came
// through, which the flattened `refs` map deliberately discards.
export type ReferenceGraphEdge = {
  src: string;
  dst: string;
  field_id: string;
};

// Forward reference adjacency for the whole project (#184 Phase 2): each node id
// → the ids it references through any entity_ref / entity_ref_list field. The
// frontend inverts this into a reverse index the view evaluator's `references`
// computed field projects over. Only referencing nodes appear as keys.
export type ReferenceGraphResponse = {
  refs: Record<string, string[]>;
  // Optional in the TS type (though the backend always sends it) so the many
  // existing `{ refs: {...} }` test mocks across the suite don't all need
  // updating for an additive field they don't exercise.
  edges?: ReferenceGraphEdge[];
};
