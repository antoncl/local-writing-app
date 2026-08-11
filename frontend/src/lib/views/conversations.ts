// The conversations-about-a-node projection (ADR-0051 S3). A chat carries a
// `subject` entity_ref (S2), so "which chats are about node X?" is the same
// reverse-reference lookup the backlinks panel runs — `projectReferences`
// over the in-memory reverse index — intersected with the chat roster to keep
// only chat nodes (and to pick up their display fields in one step).
//
// Pure and framework-free so it is unit-testable off the wire and off the DOM,
// like `candidatesToBacklinks`. The roster is already ordered pinned-first then
// `updated_at` desc (the backend list), and a filter preserves that order, so
// the result is resume-first without re-sorting here.

import type { ChatSessionSummary } from "@/lib/types";
import { projectReferences } from "@/lib/views/referenceIndex";

// The chats whose `subject` points at `subjectId`, in roster order. The reverse
// index yields every referrer of the subject (any kind); intersecting with the
// chat roster drops non-chat referrers and yields the roster summaries directly
// — no `resolveReferences` round-trip, because the roster already carries the
// title / message_count / updated_at the surface renders. A chat's only
// entity_ref field is `subject` (the type carries `subject` + `color`), so a
// chat referrer is necessarily a chat *about* this node — no field filter needed.
export function conversationsFor(
  subjectId: string | null | undefined,
  referenceIndex: ReadonlyMap<string, ReadonlySet<string>> | null | undefined,
  roster: readonly ChatSessionSummary[],
): ChatSessionSummary[] {
  if (!subjectId) return [];
  const referrers = projectReferences([subjectId], referenceIndex);
  if (referrers.size === 0) return [];
  return roster.filter((session) => referrers.has(session.id));
}
