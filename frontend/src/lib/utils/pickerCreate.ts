// "Create ‹x›" gating for NodePicker (ADR-0082 §2, F1) — kind-generic: this
// module knows nothing about tags specifically, only the create_missing
// mechanic on NodePickerConfig. Split out of NodePicker.svelte to keep that
// component under the file-size cap rather than growing it further.

import type { MetadataSchema, NodePickerConfig } from "@/lib/types";
import { pickerMembership } from "@/lib/utils/pickerSources";

export type CreateTarget = { kind: string; entryType: string };

/** The single (kind, entry_type) a config's `sources` reduce to, or null when
 * they don't: more than one kind, that kind not reducing to exactly one
 * entry_type, or the entry_type being abstract/unknown. Independent of
 * `create_missing` itself — this is the SHAPE rule alone, reused by
 * `createTargetFor` (does the config currently offer a create) and by the
 * schema editor's checkbox (`NodePickerConfigEditor` / `singleConcreteTarget`
 * naming there — could a config offer one if `create_missing` were ticked),
 * so the two can't drift.
 *
 * `entry_types[kind]` being `[]` (pickerMembership's degenerate-source
 * reduction, `pickerSources.ts`) is deliberately overloaded, mirroring the
 * backend (`NodePickerConfig.entry_types`, `models_views.py`): for FILTERING
 * it means "any entry_type of this kind" (an unconstrained source); for
 * CREATION it means "no single target" — an empty/no-constraint source names
 * no ONE type to mint, so it fails this rule the same way two named types
 * would. */
export function singleConcreteTarget(
  config: NodePickerConfig | null | undefined,
  schema: MetadataSchema | null | undefined,
): CreateTarget | null {
  const { kinds, entryTypes } = pickerMembership(config);
  if (kinds.length !== 1) return null;
  const kind = kinds[0];
  const fqns = entryTypes[kind] ?? [];
  if (fqns.length !== 1) return null;
  const entryType = fqns[0];
  const def = schema?.entry_types?.[entryType];
  if (!def || def.abstract) return null;
  return { kind, entryType };
}

/** The single (kind, entry_type) a `create_missing` config targets, or null
 * when creation isn't offered: `create_missing` unset, or the config's
 * `sources` fail `singleConcreteTarget` (see there for the shape rule).
 * Mirrors the backend's `_create_missing_shape_errors`
 * (`schema_definition_validation.py`) — a config that fails this can't have
 * saved with `create_missing: true`, so this is a render-time re-derivation
 * of the same rule, not a second one. */
export function createTargetFor(
  config: NodePickerConfig | null | undefined,
  schema: MetadataSchema | null | undefined,
): CreateTarget | null {
  if (!config?.create_missing) return null;
  return singleConcreteTarget(config, schema);
}

/** Whether `candidates` already carries a title matching `text`, trimmed and
 * case-insensitive. Candidates are expected already search-filtered by the
 * caller (the picker's own substring match already includes an exact-title
 * hit), so this only needs to check for an exact fold, not re-search. */
export function hasTitleMatch(candidates: { title: string }[], text: string): boolean {
  const needle = text.trim().toLowerCase();
  if (!needle) return false;
  return candidates.some((c) => c.title.trim().toLowerCase() === needle);
}
