// #2215 — the "Points at …" summary line for a group member's reference
// disclosure (GroupMemberTargets.svelte): reduces a picker_config to the
// comma list of type names it names, tagging a family (`descendants_of`)
// pick with "(+ subtypes)" — the same membership reduction and name lookup
// the picker/field editor already use, so the summary can't drift from what
// the tree actually shows.

import { pickerMembership } from "@/lib/utils/pickerSources";
import { entryTypeName } from "@/lib/utils/treeHelpers";
import type { MetadataSchema, NodePickerConfig } from "@/lib/types";

export function pickerTargetsSummary(
  config: NodePickerConfig | null | undefined,
  schema: MetadataSchema | null,
): string {
  const membership = pickerMembership(config);
  const labels: string[] = [];
  for (const kind of membership.kinds) {
    const fqns = membership.entryTypes[kind] ?? [];
    const families = new Set(membership.families[kind] ?? []);
    if (fqns.length === 0) {
      // A kind-only source (no entry_type leaf) — the degenerate
      // "everything of this kind" scope; no schema-level name to show.
      labels.push(kind);
      continue;
    }
    for (const fqn of fqns) {
      const name = entryTypeName(fqn, schema);
      labels.push(families.has(fqn) ? `${name} (+ subtypes)` : name);
    }
  }
  return labels.join(", ");
}
