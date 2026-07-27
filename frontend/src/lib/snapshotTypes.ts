// Snapshot / diff wire types (ADR-0043 / ADR-0044 / #439). Extracted from
// types.ts (#127/#575 branch) to keep that module under the 1500-line
// file-size cap; re-exported from `@/lib/types`, so `@/lib/types` remains the
// single import surface for callers.

/** One scene snapshot's sidecar record (ADR-0043). `id` is the snapshot's own,
 *  never the source scene's — the stored `.md` is a byte copy that still
 *  carries the source id, and conflating the two is an index collision. */
export type Snapshot = {
  id: string;
  snapshot_of: string;
  /** ISO 8601, UTC. When the *record* was made — monotonic, so the backend
   *  sorts and thins by it. **Not** what the strip lays out by. */
  captured_at: string;
  /** ISO 8601, UTC. When the *content* was written (#458).
   *
   *  This is what the strip positions and labels notches by. An automatic
   *  capture fires before the save, so its bytes are the previous sitting's —
   *  laying out by `captured_at` put a fortnight-old body at "just now", while
   *  explicit captures were dated correctly, so the two tiers meant different
   *  things on one age-laid-out track.
   *
   *  Falls back to `captured_at` server-side on snapshots taken before the
   *  field existed, so it is always populated. */
  content_written_at: string;
  /** `thinned` = automatic, subject to keep-five; `kept` = explicit, never thinned. */
  retention: "thinned" | "kept";
  /** The author's optional one-line note (#468). Original data, not the
   *  denormalized title — empty on every automatic snapshot and every explicit
   *  one taken in flow, which is the common case (ADR-0044 §L). */
  description: string;
  schema_version: number;
};

export type SnapshotList = {
  /** Oldest first — the order the strip lays out left to right. */
  snapshots: Snapshot[];
};

export type SnapshotDetail = {
  snapshot: Snapshot;
  title: string;
  body: string;
};

/** Which version the author is reading: Active · Snapshot · Both (ADR-0044 §I). */
export type DiffView = "both" | "now" | "was";

/** One provenance-tagged markdown fragment. Warm `now` = in the scene as it is;
 *  cool `was` = in the snapshot; `equal` is in both.
 *
 *  Amendment 1's contract: the text is always a complete markdown fragment, and
 *  the run is either inline-within-one-block or block-spanning, never both. */
export type DiffRun = {
  kind: "equal" | "now" | "was";
  text: string;
  /** Spans block boundaries, so it is wrapped around the RENDERED output — no
   *  inline element can wrap two paragraphs. */
  stacked?: boolean;
};

/** One field's two values. Not a diff: a value is atomic, so fields flip. */
export type FieldDiff = {
  was: unknown;
  now: unknown;
};

/** One of an entity's fields, then versus now (#439 drift axis 1). */
export type WitnessFieldDrift = {
  field_id: string;
  /** The author-facing field name, carried from the witness so the report can
   *  still name a field the schema has since dropped. */
  label: string;
  was: unknown;
  now: unknown;
  /** The value came from a live mutation marker rather than from the entry —
   *  the difference between "someone edited Tom" and "a marker in another
   *  scene changed what Tom is here". */
  from_mutation: boolean;
};

/** A recorded value's *meaning* moved under it (#439 drift axis 3). */
export type FieldReinterpretation = {
  field_id: string;
  label: string;
  type_was: string;
  type_now: string;
  options_was: string[];
  options_now: string[];
};

/** Everything that changed about one entity. Only entities where something
 *  actually fired appear — an advisory report that lists the unchanged trains
 *  the dismissal that makes it worthless. */
export type EntityDrift = {
  entity_id: string;
  /** The author's vocabulary; for a removed entity, the name at capture. */
  title: string;
  /** Axis 4, both directions. `present` = context in both versions.
   *
   *  Always `present` when the report is `truncated`: the entity cap is applied
   *  independently on each side, so the retained id sets can differ and a set
   *  difference over them would fabricate a departure. */
  membership: "added" | "removed" | "present";
  sources: string[];
  /** Axis 2. `unknown` where the change tokens cannot be compared meaningfully
   *  — never collapsed into `no`. */
  entry_changed: "yes" | "no" | "unknown";
  fields: WitnessFieldDrift[];
  reinterpreted: FieldReinterpretation[];
  /** Axis 5, non-empty only when the resolved layer actually moved. */
  layer_was: string;
  layer_now: string;
};

/** What has changed underneath a snapshot since it was taken (ADR-0043).
 *
 *  Advisory: never a gate, never an acknowledgement, never a refused restore.
 *  Three states are kept distinguishable — `available: false` (the snapshot
 *  predates the witness), `comparable: false` (recorded under a shape this
 *  build cannot read), and a real comparison whose `entities` may be empty. */
export type SnapshotDrift = {
  available: boolean;
  /** False when either side could not be read — an older witness shape, one
   *  that will not parse, or a current side that could not be built. All three
   *  mean the same thing to a reader: no claim is being made either way. */
  comparable: boolean;
  /** The entity cap fired on one of the sides, so the list may be short AND the
   *  membership axis is withheld. Must be surfaced: silence would otherwise read
   *  as "nothing else changed". */
  truncated: boolean;
  entities: EntityDrift[];
};

export type SnapshotDiff = {
  snapshot: Snapshot;
  runs: DiffRun[];
  /** Only fields whose value differs, keyed by field id. */
  fields: Record<string, FieldDiff>;
  title_was: string;
  title_now: string;
  drift: SnapshotDrift;
};
