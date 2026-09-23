// ADR-0091 §2 — the pane's grouping and defaults, derived from the diff, not
// the wire's `tier`. Pure so the exact strings and precedence rules are
// unit-tested without mounting the pane (candidateGroups.test.ts).
import type { CandidateGroup, ChangeCandidate, ChangeCandidateSet } from "@/lib/propagationTypes";

// A node with several reasons lands in the first group its reasons reach, in
// this order: declared (either reference route), else markers (a marker
// route), else mentions (a mention route, either direction).
export function groupOf(candidate: ChangeCandidate): CandidateGroup {
  const routes = candidate.reasons.map((reason) => reason.route);
  if (routes.some((route) => route === "references_source" || route === "referenced_by_source")) {
    return "declared";
  }
  if (routes.some((route) => route === "mutates_source")) return "markers";
  return "mentions";
}

function byTitleThenId(a: ChangeCandidate, b: ChangeCandidate): number {
  return a.title.toLowerCase().localeCompare(b.title.toLowerCase()) || a.id.localeCompare(b.id);
}

// A scene with a marker on a CHANGED field sorts before one whose markers are
// all on untouched fields, then by title (ADR-0091 §2).
function hasChangedMarker(candidate: ChangeCandidate): boolean {
  return candidate.reasons.some((reason) => reason.route === "mutates_source" && reason.field_changed);
}

/** The candidate set split into the pane's three groups, each sorted per
 *  ADR-0091 §2: declared and mentions by title (casefold, then id); markers
 *  puts a changed-field marker first, then the rest, each by title. */
export function groupedItems(set: ChangeCandidateSet): Record<CandidateGroup, ChangeCandidate[]> {
  const out: Record<CandidateGroup, ChangeCandidate[]> = { declared: [], markers: [], mentions: [] };
  for (const item of set.items) out[groupOf(item)].push(item);
  out.declared.sort(byTitleThenId);
  out.mentions.sort(byTitleThenId);
  out.markers.sort((a, b) => {
    const changedA = hasChangedMarker(a);
    const changedB = hasChangedMarker(b);
    if (changedA !== changedB) return changedA ? -1 : 1;
    return byTitleThenId(a, b);
  });
  return out;
}

/** Whether the change reaches prose — the body changed, or there is no
 *  baseline at all (the whole entry counts as the change). Either way every
 *  group starts kept and unfolded (ADR-0091 §2). */
export function proseStartsKept(set: ChangeCandidateSet): boolean {
  return set.body_changed || set.whole_entry;
}

/** No changed field, the body unchanged, not the whole entry, and no lane
 *  whole (a delta created since the baseline is a change even with no field
 *  named) — the ordinary case right after a confirm. */
export function nothingChanged(set: ChangeCandidateSet): boolean {
  return (
    !set.whole_entry &&
    set.changed_fields.length === 0 &&
    !set.body_changed &&
    !(set.layers ?? []).some((layer) => layer.whole)
  );
}

/** The groups that start KEPT, from the diff alone (ADR-0091 §2). */
export function defaultKept(set: ChangeCandidateSet): CandidateGroup[] {
  if (nothingChanged(set)) return [];
  if (proseStartsKept(set)) return ["declared", "markers", "mentions"];
  return ["declared", "markers"];
}

/** The groups that start FOLDED, from the diff alone (ADR-0091 §2). */
export function defaultFolded(set: ChangeCandidateSet): CandidateGroup[] {
  if (nothingChanged(set)) return ["declared", "markers", "mentions"];
  if (proseStartsKept(set)) return [];
  return ["mentions"];
}

// "a, b, c and 2 more" past three; joined plainly at or under three.
function fieldsPhrase(fields: string[]): string {
  if (fields.length <= 3) return fields.join(", ");
  return `${fields.slice(0, 3).join(", ")} and ${fields.length - 3} more`;
}

/** The one line the pane states what it did in, in ADR-0091 §2's own grammar
 *  and exact strings. `""` for the nothing-changed state — the diff column's
 *  own sentence covers it (§7, `PropagateDiff`'s nothing-changed branch). */
export function ruleLine(set: ChangeCandidateSet): string {
  if (nothingChanged(set)) return "";
  if (set.whole_entry) {
    return "No baseline: the whole entry counts as the change; everything listed starts kept.";
  }
  const fields = set.changed_fields;
  if (set.body_changed) {
    if (fields.length === 0) {
      return "The body changed: entries it names and that name it start kept, with the declared rows and the markers.";
    }
    const n = fields.length;
    return `The body and ${n} field${n === 1 ? "" : "s"} changed (${fieldsPhrase(fields)}): everything listed starts kept.`;
  }
  // Fields changed, body unchanged. `fields` can be empty here only when a
  // delta lane was created since its baseline with no field of its own named
  // (§2's whole-lane case) — the ADR names the four/five sentence forms but
  // not this cell; treated as the fields-only default with no field list to
  // name, a deliberate reading rather than a silent fallback (flagged in the
  // PR — this cell is not literally in the ADR's quoted set of sentences).
  if (fields.length === 0) {
    return "Fields changed: declared rows and markers start kept; mentions are folded.";
  }
  const n = fields.length;
  const lead = n === 1 ? "A field" : "Fields";
  return `${lead} changed (${fieldsPhrase(fields)}): declared rows and markers start kept; mentions are folded.`;
}
