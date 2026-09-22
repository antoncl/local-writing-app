// ADR-0090 wire types — the change-candidate set and the confirm (propagate)
// request/response. Extracted to keep types.ts under the file-size cap;
// re-exported from `@/lib/types` so it stays the single import surface.
// Mirrors backend/app/models/annotations.py.

import type { TodoDocument } from "./todoTypes";
import type { Snapshot } from "./snapshotTypes";

// ADR-0090 §2: the route a change-candidate reason was found by.
export type ChangeCandidateRoute =
  | "references_source"
  | "referenced_by_source"
  | "mutates_source"
  | "mentions_source";

export type ChangeCandidateTier = "declared" | "marker_untouched" | "mention";

/** One route a `ChangeCandidate` was found by. `field_id` is the referencing
 *  field for the two reference routes and the marker's field for
 *  `mutates_source`; `marker_id` and `field_changed` are `mutates_source`
 *  only — `field_changed` is whether the marker's own field is among the
 *  diff's `changed_fields` (always true when there is no baseline). */
export type ChangeCandidateReason = {
  route: ChangeCandidateRoute;
  field_id: string;
  marker_id: string;
  field_changed: boolean;
};

/** One dependent of a settled change, with every route that found it. A node
 *  reachable by more than one route appears once. */
export type ChangeCandidate = {
  id: string;
  kind: string;
  entry_type: string;
  title: string;
  tier: ChangeCandidateTier;
  reasons: ChangeCandidateReason[];
};

/** The candidate set for one settled lore change — a list of `(node, reasons)`
 *  and nothing else; no score, no threshold, no cut. `whole_entry=true` (no
 *  baseline given) means every field counts as changed. */
export type ChangeCandidateSet = {
  source_id: string;
  baseline_snapshot_id: string;
  changed_fields: string[];
  body_changed: boolean;
  whole_entry: boolean;
  items: ChangeCandidate[];
};

/** The confirm step's write: the candidates the writer kept, measured
 *  against the same baseline semantics as the read-only candidate endpoint.
 *  `kept` may not be empty. */
export type PropagateRequest = {
  baseline_snapshot_id?: string | null;
  kept: string[];
};

/** What confirming a propagation writes, and nothing else: one review item
 *  per kept candidate, in candidate order, and the new baseline snapshot of
 *  the source. No dependent's file is touched. */
export type PropagateResponse = {
  todos: TodoDocument;
  created: string[];
  snapshot: Snapshot;
};
