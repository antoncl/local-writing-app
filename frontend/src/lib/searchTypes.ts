// Search + replace wire types (ADR-0085). Extracted from types.ts to keep
// that barrel under the file-size cap; re-exported from `@/lib/types` so it
// stays the single import surface.

export type SearchHit = {
  // ADR-0085 §2: the index's kind (or the synthetic "project" TODO bucket),
  // not a closed set — a hit always opens through the node's own kind.
  kind: string;
  entry_type?: string;
  file_id: string;
  path: string;
  line: number;
  excerpt: string;
  todo_id?: string | null;
  field: "body" | "metadata";
  start: number;
  end: number;
  revision: string;
  owned: boolean;
  // The matched text itself (ADR-0085 §4 rule 2): lets a replace verify the
  // range still matches what the query found before writing through it. Empty
  // for a metadata hit — those never replace.
  text: string;
};

// One hit a replace asks the backend to apply — the anchor `SearchHit` carried
// back (ADR-0085 §4). `field` rides along so a metadata hit sent by mistake (or
// a stale client) reports `not_replaceable/metadata` instead of being dropped.
export type ReplaceHitRef = {
  file_id: string;
  field: "body" | "metadata";
  start: number;
  end: number;
  text: string;
  revision: string;
};

export type ReplaceStatus = "replaced" | "stale" | "not_replaceable";

// One hit's fate (ADR-0085 §4): `reason` names why a `not_replaceable`/`stale`
// hit didn't write; `revision` is the node's new save revision after a
// `replaced` write, else absent.
export type ReplaceOutcome = {
  file_id: string;
  start: number;
  end: number;
  status: ReplaceStatus;
  reason?: string | null;
  detail?: string | null;
  revision?: string | null;
};

export type ReplaceResponse = {
  outcomes: ReplaceOutcome[];
  replaced_nodes: number;
};
