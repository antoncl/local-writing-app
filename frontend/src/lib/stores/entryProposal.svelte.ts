// The entry-pane end of the entry-patch brainstorm review (ADR-0046 slice 3;
// generalized to any schema-typed node, ADR-0048 §5), as a per-instance rune
// controller — the shape `LoreScrubController` / `SnapshotStripController` use,
// and NodeEditor already composes.
//
// A `revise:entry` brainstorm (launched from EntryBrainstormBar) commits an
// `EntryPatch` into the `entryBrainstorm` cross-pane store. This controller
// derives the proposed-vs-current flips for the open node — the body plus
// each changed `long_text` field as prose run-diffs (`fields`), and each changed
// structured field as an atomic rail flip (`structuredFlips`, slice 3b) — and
// **owns the review as a transaction** (#634).
//
// The controller is a pure, kind-agnostic mechanism: it keys off the fed node id
// and schema, never the node's `kind`. Which kinds may launch a brainstorm is the
// host's (NodeEditor's) policy — the controller reviews whatever proposal exists.
//
// **The review is a frozen, save-on-Done transaction.** While a proposal is up
// the host freezes the entry (autosave off, rail/title read-only), so the diff's
// "current" side cannot move under the review. Accepting a unit (a body/long_text
// region here) records "take proposed here" in the controller's *resolution*
// state and writes nothing. There is exactly ONE write, on `commit()` (the Done
// gesture, or "Save" from the close guard), which applies the accumulated patch
// through the host's buffer and then flushes it as a single explicit PUT.
// `abandon()` (Discard / "Don't save") drops it all and writes nothing — the
// entry was frozen, so no authored work is at risk.
//
// **Adopting is still the host's job**, exactly as `SnapshotStripController`'s
// callbacks are: the controller decides only WHAT the patch touches and WHEN to
// write, never how. The host merges the fields into its own metadata state,
// adopts the body through its prose buffer, and issues the explicit flush.
import type { DiffView, EntryMetadata, MetadataFieldType, MetadataSchema, MetadataValue } from "@/lib/types";
import type { FieldFlip } from "@/lib/utils/entryRevision";
import { entryBrainstorm } from "@/lib/stores/entryBrainstorm.svelte";

/** One structured (non-prose) field the patch proposes, reviewed as an atomic
 *  `{was, now}` flip in the frozen rail (ADR-0046 §2 / slice 3b): the value is
 *  swapped whole, never run-diffed. `was` is the proposed candidate (the cool
 *  side), `now` the entry's current value (the warm side). */
export type StructuredFlip = {
  fieldId: string;
  was: MetadataValue;
  now: MetadataValue;
};

// Field types that are NOT an atomic structured flip. `long_text` (and the body)
// take the prose run-diff instead (§2, handled by `fields` below); `computed` and
// the two `entity_ref` shapes are never AI-proposed (§4) — the backend drops them
// from a patch, and this mirrors that so a stray one can't render as a flip. Every
// other proposable type — `text`/`number`/`boolean`/`date`/`select`/
// `multi_select`/`tags`/`color`/`list` — flips atomically (a `list` flips as the
// whole proposed list, rendered read-only by ListValueEditor; per-item flip
// presentation is a #698 follow-up, the backend already salvages per item).
// Dispatch by type alone, so a user-added field is indistinguishable from a
// built-in one (§2).
const NON_STRUCTURED_TYPES: ReadonlySet<MetadataFieldType> = new Set<MetadataFieldType>([
  "long_text",
  "computed",
  "entity_ref",
  "entity_ref_list",
]);

// Structural identity fields that can never flip: `id` (opaque) and `entry_type`
// (retyping is a different gesture). Mirrors the backend's non-proposable ids so
// a stray one can't render. Note `title` is NOT here — an AI-proposed rename IS
// adoptable; it rides the flip like any other field and the backend applies the
// rename on save, so `title` flips and routes through the host's title state.
const NON_FLIPPABLE_FIELD_IDS: ReadonlySet<string> = new Set(["id", "entry_type"]);

export class EntryProposalController {
  // Fed by the host each render — the derivations below track these. `nodeId` is
  // the open node's id (any kind); the review is keyed on it, never on the kind.
  nodeId = $state<string | null>(null);
  schema = $state<MetadataSchema | null>(null);
  metadata = $state<EntryMetadata>({});

  // Wired by the host — the write side of a commit (see the module note).
  onAdoptFields: ((fields: Record<string, MetadataValue>) => void) | null = null;
  onAdoptBody: ((body: string) => void | Promise<void>) | null = null;
  onEmitChange: (() => void) | null = null;
  // Wired by the host — the ONE explicit post that ends the transaction: cancel
  // the (frozen) autosave timer and PUT the pane once. Runs after the patch has
  // been applied to the buffer, so it captures body + metadata in a single write.
  // Returns whether the post landed — `false` (e.g. a changed-on-disk 409) keeps
  // the review open with its adoptions intact rather than dropping the patch.
  onFlush: (() => Promise<boolean> | void) | null = null;
  // Wired by the host — reads the LIVE buffer (not the saved file), the side the
  // body flip compares against. A callback, not fed state, because the host owns
  // the prose buffer (mirrors `SnapshotStripController.readLive`).
  readCurrentBody: (() => string) | null = null;

  /** The patch committed for the open node, or null. Purely proposal-driven —
   *  a node reviews iff a brainstorm committed a patch for its id. */
  proposal = $derived(
    this.nodeId ? entryBrainstorm.proposalFor(this.nodeId) : null,
  );

  /** The `long_text` fields the patch proposes, paired with their current value —
   *  each reviewed as its own run-diff flip. Structured fields go to
   *  `structuredFlips` (atomic, rail-rendered); the body is handled separately. */
  fields = $derived.by((): FieldFlip[] => {
    const proposal = this.proposal;
    const schema = this.schema;
    if (!proposal || !schema) return [];
    const flips: FieldFlip[] = [];
    for (const [fieldId, proposedValue] of Object.entries(proposal.fields)) {
      const field = schema.fields[fieldId];
      if (!field || field.type !== "long_text") continue;
      const current = this.metadata[fieldId];
      flips.push({
        fieldId,
        label: field.name ?? fieldId,
        currentValue: typeof current === "string" ? current : "",
        proposedValue: typeof proposedValue === "string" ? proposedValue : "",
      });
    }
    return flips;
  });

  /** The structured (non-prose) fields the patch proposes, each an atomic flip
   *  reviewed in the frozen rail (slice 3b). Excluded: `long_text` (run-diff,
   *  above) and the body (separate); the non-proposable value types; the
   *  structural `id`/`entry_type`; and `hidden` fields — the backend already
   *  neither offers nor accepts a hidden field, and the rail can't render one, so
   *  a stray proposal for one is simply ignored. `title` DOES flip — an adopted
   *  rename rides through like any field (§host routes it to the title state).
   *  `now` reads the frozen `metadata` (fed title/status too), so the diff can't
   *  drift. */
  structuredFlips = $derived.by((): StructuredFlip[] => {
    const proposal = this.proposal;
    const schema = this.schema;
    if (!proposal || !schema) return [];
    const flips: StructuredFlip[] = [];
    for (const [fieldId, proposedValue] of Object.entries(proposal.fields)) {
      const field = schema.fields[fieldId];
      if (!field || field.hidden || NON_FLIPPABLE_FIELD_IDS.has(fieldId)) continue;
      if (NON_STRUCTURED_TYPES.has(field.type)) continue;
      flips.push({ fieldId, was: proposedValue, now: this.metadata[fieldId] ?? null });
    }
    return flips;
  });

  /** The structured flips as MetadataPanel's `compare.fields` map — the same
   *  `{was, now}` shape its snapshot-compare lens renders, so the rail reuses the
   *  existing `.flipped` tint (ADR-0046 §2). */
  structuredCompareFields = $derived.by((): Record<string, { was: MetadataValue; now: MetadataValue }> => {
    const out: Record<string, { was: MetadataValue; now: MetadataValue }> = {};
    for (const flip of this.structuredFlips) out[flip.fieldId] = { was: flip.was, now: flip.now };
    return out;
  });

  /** Something to review only when the patch touches the body, a `long_text`
   *  field, or a structured field. (A patch that proposes only non-proposable
   *  fields reaches here empty; ChatBodyView already told the author so.) */
  hasReview = $derived(
    !!this.proposal &&
      (this.proposal.body != null || this.fields.length > 0 || this.structuredFlips.length > 0),
  );

  // ---- review-local resolution (the accumulation, never a write) -------------
  //
  // The running "take proposed here" decision per reviewable unit. The body key
  // is separate from field ids so a field literally named "body" can't collide.
  // `null` means "unchanged from current" (declined / not yet touched). These
  // never touch `metadata`, so the frozen diff cannot drift as the author works.
  resolvedBody = $state<string | null>(null);
  resolvedText = $state<Record<string, string | null>>({});
  // A structured field flip is adopted whole (§2): the boolean is "take the
  // proposed value", and the value itself comes from `structuredCompareFields`.
  // A boolean, not the value, so a proposal that clears a field to `null` is
  // still distinguishable from "declined" (both would be null-valued otherwise).
  adoptedStructured = $state<Record<string, boolean>>({});

  // ---- the judge axis: which whole version the prose flips render (#710) -----
  //
  // The same three-state view the snapshot compare drives (`SnapshotStripController
  // .view`): `both` interleaves the diff (merge), `was` shows the AI's proposal
  // whole and `now` shows the current text whole (judge). The prose flips honour it
  // through the shared `renderDiffRuns(runs, view)`; the structured rail is left on
  // its adopt lens, which already shows the proposed value AND a "Current:" hint,
  // so a version toggle would tell it nothing the row does not already say. Unlike
  // the snapshot (which keeps the view across notch steps), a new proposal resets
  // to `both` — see `resetResolution`.
  view = $state<DiffView>("both");

  /** Read one whole version, or `both` to interleave the diff (the snapshot's
   *  A·S·B, ADR-0044 §I). A pure render switch — it changes nothing but which
   *  runs the prose flips show. */
  setView(view: DiffView): void {
    this.view = view;
  }

  /** `now`/`was` toggle against `both`, so one gesture both enters and leaves a
   *  single version — the snapshot's `toggleView`. */
  toggleView(view: "now" | "was"): void {
    this.view = this.view === view ? "both" : view;
  }

  /** Which whole side the structured rail reads when the author is reading one
   *  version (the snapshot's `fieldSide`). `both` is the interactive adopt lens
   *  and has no single side, so the host only consults this for `now`/`was`. */
  fieldSide(): "now" | "was" {
    return this.view === "was" ? "was" : "now";
  }

  /** A body flip reports its running resolution (null while unchanged). */
  setBodyResolution(value: string | null): void {
    this.resolvedBody = value;
  }

  /** A `long_text` field flip reports its running resolution (null while
   *  unchanged). */
  setFieldResolution(fieldId: string, value: string | null): void {
    this.resolvedText = { ...this.resolvedText, [fieldId]: value };
  }

  /** Whether a structured field flip is adopted (take the proposed value). */
  isStructuredAdopted(fieldId: string): boolean {
    return this.adoptedStructured[fieldId] === true;
  }

  /** Toggle a structured field flip between adopted and declined — the rail's
   *  click-to-adopt gesture (the atomic twin of accepting a prose region). */
  toggleStructured(fieldId: string): void {
    this.adoptedStructured = {
      ...this.adoptedStructured,
      [fieldId]: !this.adoptedStructured[fieldId],
    };
  }

  /** Take the whole candidate — the mirror of the snapshot's atomic `restore()`
   *  (#710). Marks every reviewable unit adopted: the body and each `long_text`
   *  field resolve to their whole proposed value, every structured flip to
   *  adopted. It only ACCUMULATES — the host follows it with `commit()`, so the
   *  whole-adopt still lands as the same single PUT as a hand-picked one (§1).
   *  Its opposite, "reject all", is `abandon()`: keep the current version whole,
   *  write nothing — the pair the review surfaces as one gesture each. */
  acceptAll(): void {
    const proposal = this.proposal;
    if (!proposal) return;
    if (proposal.body !== null) this.resolvedBody = proposal.body;
    const text: Record<string, string | null> = {};
    for (const flip of this.fields) text[flip.fieldId] = flip.proposedValue;
    this.resolvedText = text;
    const structured: Record<string, boolean> = {};
    for (const flip of this.structuredFlips) structured[flip.fieldId] = true;
    this.adoptedStructured = structured;
  }

  /** Whether the author has adopted anything — the "you have changes" signal the
   *  close guard reads to decide between a silent discard and the Save prompt. */
  hasPendingChanges = $derived(
    this.resolvedBody !== null ||
      Object.values(this.resolvedText).some((v) => v !== null) ||
      Object.values(this.adoptedStructured).some((v) => v),
  );

  /** Drop the accumulated resolution. Called on commit/abandon and by the host
   *  whenever the proposal identity changes, so a superseding commit starts
   *  clean instead of inheriting the previous review's adoptions. */
  resetResolution(): void {
    this.resolvedBody = null;
    this.resolvedText = {};
    this.adoptedStructured = {};
    // A fresh review opens on the interleaved diff — the judge toggle is a
    // per-review reading choice, not carried across proposals (#710).
    this.view = "both";
  }

  /** The body the author currently sees (live buffer, not the saved file) — the
   *  side the body flip compares against, buffer-safe like the snapshot compare.
   *  Captured once at review mount, so it is frozen for the review's life. */
  currentBody(): string {
    return this.readCurrentBody?.() ?? "";
  }

  /** Commit the reviewed patch in ONE explicit write — the Done gesture, or
   *  "Save" from the close guard. Merge the adopted field values into the host's
   *  metadata, adopt the body through its buffer, then flush the pane once so
   *  body + metadata land in a single PUT through the node's own save endpoint
   *  (ADR-0046 §1). A commit with nothing adopted is a plain dismiss (no write),
   *  exactly like "Close". */
  async commit(): Promise<boolean> {
    const fields: Record<string, MetadataValue> = {};
    for (const [fieldId, value] of Object.entries(this.resolvedText)) {
      if (value !== null) fields[fieldId] = value;
    }
    // Adopted structured flips take the proposed value whole (§2). Read it from
    // the compare map so the boolean-only resolution stays the single source of
    // "adopted", and a proposal that clears a field to `null` still writes.
    const proposedById = this.structuredCompareFields;
    for (const [fieldId, adopted] of Object.entries(this.adoptedStructured)) {
      if (adopted && fieldId in proposedById) fields[fieldId] = proposedById[fieldId].was;
    }
    const body = this.resolvedBody;
    const hasFields = Object.keys(fields).length > 0;
    if (hasFields || body !== null) {
      if (hasFields) this.onAdoptFields?.(fields);
      if (body !== null) await this.onAdoptBody?.(body);
      // Package body + metadata into the pane draft, then the single explicit
      // post. Unconditional so the fields-only path (no body) still writes.
      this.onEmitChange?.();
      // If the post fails, keep the review open with its adoptions intact — the
      // transaction is only "done" once the write lands, so don't clear the
      // proposal and lose the patch.
      if ((await this.onFlush?.()) === false) return false;
    }
    this.resetResolution();
    this.clear();
    return true;
  }

  /** Discard the review — "Don't save" / Discard. Nothing was written during the
   *  frozen review, so this only drops the proposal and the accumulated
   *  resolution; the entry is left exactly as it was. */
  abandon(): void {
    this.resetResolution();
    this.clear();
  }

  /** Dismiss the proposal for the open node. Low-level: prefer commit/abandon,
   *  which also clear the resolution. */
  clear(): void {
    if (this.nodeId) entryBrainstorm.clear(this.nodeId);
  }
}
