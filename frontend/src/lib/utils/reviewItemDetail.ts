// The reason-grammar line for an ADR-0090 review item — shared between the
// Todo pane's file-TODO row and `ReviewItemsPanel`'s computed-field tab, so
// the two surfaces describe the same `TodoSource` the same way. Unlike the
// confirm surface's per-candidate detail (`PropagatePane.svelte`, built from
// the full `ChangeCandidateReason` set with a field id), a review item's
// `TodoSource` carries only the FIRST reason's route (ADR-0090 §3) — no
// field id — so the phrase names the route, not the field.
import type { ChangeCandidateRoute, TodoSource } from "@/lib/types";

const REASON_PHRASE: Record<ChangeCandidateRoute, string> = {
  references_source: "refers to the change",
  referenced_by_source: "referenced by the change",
  mutates_source: "⤳ a marker on the change",
  mentions_source: "mentions the change",
};

/** "<phrase> · from <source title>" — the whole detail line for a review
 *  item, given its source and the source's resolved title (or its bare id,
 *  when no lookup is cheap). */
export function reviewItemSourceDetail(source: TodoSource, sourceTitle: string): string {
  return `${REASON_PHRASE[source.reason]} · from ${sourceTitle}`;
}
