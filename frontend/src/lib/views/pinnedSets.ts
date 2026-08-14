// The pinned-sets-about-an-entity projection (ADR-0055 §3). A mutation set may
// carry a `target_entity` entity_ref pinning it to a character; "which sets are
// pinned to entity X?" is the same reverse-reference lookup `conversationsFor`
// runs — `projectReferences` over the in-memory reverse index — intersected
// with the mutation-set roster to keep only mutation-set nodes.
//
// Pure and framework-free so it is unit-testable off the wire and off the DOM,
// like `conversationsFor`. The roster is title-sorted (the backend list order),
// and a filter preserves that order, so no re-sorting here.

import type { MutationSetEntrySummary } from "@/lib/types";
import { projectReferences } from "@/lib/views/referenceIndex";

// The mutation sets whose `target_entity` points at `entityId`, in roster order.
// The reverse index yields every referrer of the entity (any kind); intersecting
// with the mutation-set roster drops non-set referrers (chats, other lore) and
// yields the roster summaries directly. A mutation set's only entity_ref field is
// `target_entity`, so a mutation-set referrer is necessarily *pinned to* this
// entity — no field filter needed (the same argument `conversationsFor` makes
// for a chat's sole `subject` ref).
export function pinnedSetsFor(
  entityId: string | null | undefined,
  referenceIndex: ReadonlyMap<string, ReadonlySet<string>> | null | undefined,
  roster: readonly MutationSetEntrySummary[],
): MutationSetEntrySummary[] {
  if (!entityId) return [];
  const referrers = projectReferences([entityId], referenceIndex);
  if (referrers.size === 0) return [];
  return roster.filter((set) => referrers.has(set.id));
}
