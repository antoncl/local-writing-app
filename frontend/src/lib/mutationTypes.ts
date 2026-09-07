// Mid-scene mutation + mutation-set wire types. Extracted from types.ts to
// keep that barrel under the file-size cap; re-exported from `@/lib/types` so
// it stays the single import surface.

// Mid-scene lore mutation records (#33). A marker sets one field of one lore
// entry to a new value at a prose position; the timeline is manuscript-ordered.
export type MutationMarkerRecord = {
  marker_id: string;
  entity_id: string;
  field: string;
  op: string; // "replace" (default) | "add" | "remove" (#58)
  value: string;
  name: string; // optional human label (#65)
  group: string; // co-authored-set tie (#65, legacy)
  unit_id: string; // the authored unit this record belongs to (#69, ADR-0016)
  unit_name: string; // the unit's human label from the carrier head
  scene_id: string;
  offset: number;
  line: number;
  scene_path: string;
};

export type MutationMarkerList = {
  items: MutationMarkerRecord[];
};

// Reusable mutation set (#62): a body-less Node kind — an ordered list of
// (field, op, value) rows + a target lore entry-type. The entity is bound at
// apply time (a template), and applying expands to independent inline markers.
export type MutationSetRow = {
  field: string;
  op: string; // "replace" | "add" | "remove"
  value: string;
};

export type MutationSetEntrySummary = {
  id: string;
  title: string;
  entry_type: string;
  target_entry_type: string;
  // ADR-0055 §3: optional entity pin. "" = a reusable template (entity bound at
  // apply time); set = an entity-pinned one-off (offered only for its own
  // entity, stamped on apply). Stored as the `target_entity` metadata entity_ref.
  target_entity: string;
  row_count: number;
  // ADR-0055 §5: a pinned set is a one-off — once placed in a scene it drops
  // from the card's pending list (kept as the chat's provenance). Always false
  // for a reusable set; apply never marks it.
  placed: boolean;
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
  // ADR-0055 §5 placement state — see MutationSetEntrySummary.placed.
  placed: boolean;
  source_layer_id: string;
  source_layer_label: string;
};

export type MutationSetEntryList = {
  entries: MutationSetEntrySummary[];
};

export type EffectiveStateResponse = {
  entity_id: string;
  scene_id: string;
  position: number | null;
  // Scalar fields resolve to a string; collection fields to a string[] (ADR-0009).
  values: Record<string, string | string[]>;
};
