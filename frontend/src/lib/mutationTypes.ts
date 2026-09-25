// Mid-scene mutation + mutation-set wire types. Extracted from types.ts to
// keep that barrel under the file-size cap; re-exported from `@/lib/types` so
// it stays the single import surface.

import type { MetadataValue } from "./metadataTypes";

// Mid-scene lore mutation records (#33, ADR-0095 §1/§3/§5). A resolved record
// is one mutation-SET ROW joined at the scene ANCHOR that places it; the
// timeline is manuscript-ordered. `marker_id = "<anchor_id>.<row_id>"` is the
// `(anchor, row)` identity everything that keys on a record — closes,
// `exclude`, the change-candidate dedupe, review items, the scrubber's stops
// — keys on. `unit_id` is the anchor id (the pill/timeline/scrubber grouping
// granularity); `unit_name`/`name` are the set's title (may be "").
export type MutationMarkerRecord = {
  marker_id: string;
  entity_id: string;
  field: string;
  op: string; // "replace" (default) | "add" | "remove" (#58)
  value: string;
  name: string; // the set's title (may be "")
  group: string; // co-authored-set tie (#65, legacy — read-only survivor)
  unit_id: string; // the anchor id this record belongs to (ADR-0095 §1)
  unit_name: string; // the set's title, echoed
  // ADR-0095 §3: the record's identity components. Optional here (default
  // "", mirrors the backend model) so existing fixtures that predate this
  // slice keep type-checking without every literal naming them.
  anchor_id?: string;
  set_id?: string;
  row_id?: string;
  scene_id: string;
  offset: number;
  line: number;
  scene_path: string;
};

export type MutationMarkerList = {
  items: MutationMarkerRecord[];
};

// One field-change row of a mutation set (ADR-0095 §3): a `(field, op,
// value)` triple, `id` its stable identity within the set — a copied set
// keeps its rows' ids (the anchor id tells the copies apart).
export type MutationSetRow = {
  field: string;
  op: string; // "replace" | "add" | "remove"
  value: string;
  id: string;
};

// One place a set is anchored (ADR-0095 §1/§2): the anchor comment's own id,
// the scene it lives in, and that scene's title for display.
export type MutationSetAnchor = {
  anchor_id: string;
  scene_id: string;
  scene_title: string;
};

export type MutationSetState = "template" | "staged" | "active";

export type MutationSetEntrySummary = {
  id: string;
  title: string;
  entry_type: string;
  target_entry_type: string;
  // ADR-0055 §3: optional entity pin. "" = a reusable template (entity bound at
  // apply time); set = an entity-pinned one-off. Stored as the `target_entity`
  // metadata entity_ref.
  target_entity: string;
  row_count: number;
  // ADR-0095 §2: computed from the pin and the anchor scan, never stored.
  anchors: MutationSetAnchor[];
  state: MutationSetState;
  // A pin that names a lore entry no longer in the node index: a dead pin,
  // unlike a missing one, keeps the set out of the template list.
  pin_missing: boolean;
  source_layer_id: string;
  source_layer_label: string;
};

export type MutationSetEntry = {
  id: string;
  title: string;
  revision: string;
  entry_type: string;
  target_entry_type: string;
  // ADR-0055 §3 entity pin — see MutationSetEntrySummary.target_entity.
  target_entity: string;
  rows: MutationSetRow[];
  // ADR-0095 §2 — see MutationSetEntrySummary.
  anchors: MutationSetAnchor[];
  state: MutationSetState;
  pin_missing: boolean;
  source_layer_id: string;
  source_layer_label: string;
};

export type MutationSetEntryList = {
  entries: MutationSetEntrySummary[];
};

// ADR-0095 §6: `POST /api/mutation-sets/{id}/copy` result — the copy, plus
// any rows dropped because they no longer validate against the (re-)pinned
// entity's type.
export type CopyMutationSetResult = {
  entry: MutationSetEntry;
  dropped_rows: MutationSetRow[];
};

// One field's effective value (ADR-0089 §3): scalar → string; flat
// collection → string[]; list field → its folded items (each item a
// member-key → value map).
export type EffectiveFieldValue = string | string[] | Record<string, MetadataValue>[];

export type EffectiveStateResponse = {
  entity_id: string;
  scene_id: string;
  position: number | null;
  // Scalar → string; flat collection → string[]; list field → its folded
  // items (ADR-0089 §3).
  values: Record<string, EffectiveFieldValue>;
};
