// Entry-patch (ADR-0046) wire types. Extracted from types.ts to keep that
// barrel under the file-size cap; re-exported from `@/lib/types` so it stays
// the single import surface.

import type { MetadataValue } from "./metadataTypes";

// ADR-0046 §1: a proposed entry state committed by a brainstorm — the entry's
// revised body (optional) plus proposed field values. The cross-pane store
// carries this; the review dispatches by field type (body + long_text as
// run-diff flips in slice 3a, structured fields as atomic flips in 3b).
// How an entry-patch proposal should be REVIEWED before it commits — the
// `commit.review` axis declared on the launching prompt (ADR-0054 §2; ADR-0051
// S5-next). `visual_diff` is the per-run adopt flip (ADR-0046 default); `replace`
// is a plain current→proposed swap of the whole field, for a value regenerated
// from scratch (a scene summary) where a run-diff would be noise.
export type ReviewMode = "visual_diff" | "replace";

export type EntryPatch = {
  body: string | null;
  fields: Record<string, MetadataValue>;
  // Set client-side at propose time from the launching prompt's `commit.review`
  // (ChatBodyView); the backend patch response never carries it. Absent ⇒ the
  // default `visual_diff` review. The `replace` path also strips `body` so a
  // whole-field regenerate can never rewrite a scene's prose.
  reviewMode?: ReviewMode;
};

// The validated patch returned by POST /api/ai/entry-patch/{id}. `dropped` names
// fields the model proposed that were rejected (unknown / illegal / non-
// proposable); `garbled` is true when the reply wasn't a JSON object at all.
export type AIEntryPatch = EntryPatch & {
  dropped: string[];
  garbled: boolean;
};

// The result of a fresh-extraction commit (ADR-0051 S4): the server rebuilt the
// format contract from the target's schema and ran it as its own pass over the
// transcript, then validated the reply. `patch` is null and `ok` false when the
// extraction turn itself failed or returned nothing (distinct from a `garbled`
// patch, which round-trips so the author is told to finalize again). `cost_usd`
// is the extraction turn's cost, attributed to the session by the caller.
export type EntryPatchExtraction = {
  patch: AIEntryPatch | null;
  cost_usd: number | null;
  ok: boolean;
  error: string | null;
};
