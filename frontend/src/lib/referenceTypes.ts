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

// Forward reference adjacency for the whole project (#184 Phase 2): each node id
// → the ids it references through any entity_ref / entity_ref_list field. The
// frontend inverts this into a reverse index the view evaluator's `references`
// computed field projects over. Only referencing nodes appear as keys.
export type ReferenceGraphResponse = {
  refs: Record<string, string[]>;
};
