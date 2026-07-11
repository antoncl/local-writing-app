// Backlinks-panel-as-a-view (#194, Phase 2c of #184). The panel is the view
// `field_of($self, references)` with `$self` = the open node: its members are
// that node's referrers, read straight from the in-memory reverse index (the
// same `projectReferences` the evaluator runs for the `references` computed
// field). Presentation reuses `resolve_references` to turn referrer ids into
// display rows — cross-kind and authoritative, like the retired per-node
// `list_backlinks` node-index walk.
//
// Any-field by construction: the reverse index carries no per-field split, so a
// node referencing the anchor through two fields collapses to one row (the old
// endpoint emitted one row per matching field). That matches `references` being
// an any-field computed field; field-specific backlinks are a forward `Filter`.

import type { Backlink, ReferenceCandidate } from "@/lib/types";
import { api } from "@/lib/api";
import { projectReferences } from "@/lib/views/referenceIndex";

// Map resolved referrer candidates → panel rows, sorted by kind then title for a
// stable panel (mirroring the old endpoint's ordering). `field_id`/`field_name`
// are empty — membership is any-field, so there is no single field to attribute;
// the panel keys rows on `id:field_id`, which stays unique because referrer ids
// are already deduped. Pure, so the mapping/sort is unit-testable off the wire.
//
// Two exclusions match the retired `list_backlinks` (#203): the anchor node's own
// id (a node referencing itself is not its own backlink — `if entry.id ==
// target_id: continue`), and `found: false` candidates (a referrer deleted during
// the stale-index window, which the endpoint never emitted a row for — it would
// render as a broken empty-kind row).
export function candidatesToBacklinks(
  candidates: readonly ReferenceCandidate[],
  anchorId?: string,
): Backlink[] {
  return candidates
    .filter((c) => c.found && c.id !== anchorId)
    .map((c) => ({ id: c.id, title: c.title, kind: c.kind, entry_type: c.entry_type, field_id: "", field_name: "" }))
    .sort((a, b) => a.kind.localeCompare(b.kind) || a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
}

// Resolve the open node's backlinks. `anchorId` binds `$self`; `referenceIndex`
// is the project-wide reverse index (see `stores/references`).
export async function backlinksFor(
  anchorId: string,
  referenceIndex: ReadonlyMap<string, ReadonlySet<string>> | null | undefined,
): Promise<Backlink[]> {
  const referrerIds = [...projectReferences([anchorId], referenceIndex)];
  if (referrerIds.length === 0) return [];
  const { candidates } = await api.resolveReferences(referrerIds);
  return candidatesToBacklinks(candidates, anchorId);
}
