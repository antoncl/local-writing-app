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
  // The excerpt is a window around the match (#1868); these say whether the
  // backend clipped text before/after it. The pane renders the ellipses itself,
  // OUTSIDE the highlighted text, so a query of "…" can't mark them.
  clipped_before?: boolean;
  clipped_after?: boolean;
  todo_id?: string | null;
  field: "body" | "metadata";
  start: number;
  end: number;
  revision: string;
  owned: boolean;
  // The matched text itself (ADR-0085 §4 rule 2): lets a replace verify the
  // range still matches what the query found before writing through it. Empty
  // for a find-only metadata hit.
  text: string;
  // A metadata hit inside stored free text (ADR-0085 Amendment 2): the key path
  // to that string (`["summary"]`, `["follow_ups", 2]`, `["beats", 1, "note"]`),
  // with `start`/`end` into it. Absent/null for a body hit and for a find-only
  // metadata hit (title, reference, select …), which never replaces.
  metadata_path?: (string | number)[] | null;
};

// One hit a replace asks the backend to apply — the anchor `SearchHit` carried
// back (ADR-0085 §4). `field` rides along so a find-only metadata hit sent by
// mistake (or a stale client) reports `not_replaceable/metadata` instead of
// being dropped; `metadata_path` marks a text-slot hit, which replaces.
export type ReplaceHitRef = {
  file_id: string;
  field: "body" | "metadata";
  start: number;
  end: number;
  text: string;
  revision: string;
  metadata_path?: (string | number)[] | null;
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
