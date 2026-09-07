// Manuscript structure + scene wire types. Extracted from types.ts to keep
// that barrel under the file-size cap; re-exported from `@/lib/types` so it
// stays the single import surface.

import type { MetadataValue, EntryMetadata } from "./metadataTypes";
import type { Backlink } from "./referenceTypes";

export type StructureNode = {
  id: string;
  type: string;
  title: string;
  scene_id?: string | null;
  // Scene's current status value (e.g. "draft"). Used by the tree to
  // render a colored left-edge stripe by looking up the matching option
  // in metadataSchema.fields.status. Null for non-leaf nodes.
  status?: string | null;
  // Scene's instance-level color override (palette swatch id).
  color?: string | null;
  // Full scene front-matter metadata (pov, characters, location, …) surfaced
  // so the view evaluator can filter the Draft roster by scene fields in one
  // pass (#184 Phase 3). Null for non-scene nodes.
  metadata?: Record<string, MetadataValue> | null;
  computed_metadata?: Record<string, MetadataValue>;
  // ADR-0079: for each schema `cascade_fields` id, this node's RESOLVED value
  // folded down the manuscript structure (own → nearest ancestor → book default →
  // unset) with provenance. `source_id` null = book default; `own` true = this node
  // set it. Derived, never written. Null when the schema declares no cascade_fields.
  resolved_cascade?: Record<string, ResolvedCascadeField> | null;
  children: StructureNode[];
};

// One resolved cascade field (ADR-0079): the folded value + where it came from.
// `overrides` = this node's own value SHADOWS a value it would otherwise inherit
// (drives the override mark, #1734); `inherited_source_id` = whose value it
// shadows (null = the book), for the "reset to inherited" label.
export type ResolvedCascadeField = {
  value: MetadataValue | null;
  source_id: string | null;
  own: boolean;
  overrides: boolean;
  inherited_source_id: string | null;
};

export type StructureDocument = {
  root: StructureNode;
};

export type Scene = {
  id: string;
  title: string;
  body: string;
  revision: string;
  status: string;
  entry_type: string;
  metadata: EntryMetadata;
  computed_metadata: EntryMetadata;
  source_layer_id?: string;
  source_layer_label?: string;
};

// A scene file on disk that no manuscript node references — a pending import
// offer (#4), not an error. Its own read now (#635), not a validation field.
export type LooseScene = { id: string; title: string; filename: string };

// A lore entry whose whole body is a single fenced code block (#1628) — a paste
// artifact that renders prose as monospaced source. Reported as a flag, not a
// repair: the modal offers an explicit, reviewable unwrap.
export type CodeFencedBody = { id: string; kind: string; title: string };

export type StructureNodeDeletePreview = {
  target_id: string;
  target_title: string;
  target_type: string;
  descendant_scene_count: number;
  descendant_container_count: number;
  backlinks: Backlink[];
};
