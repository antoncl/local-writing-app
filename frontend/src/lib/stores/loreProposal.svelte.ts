// The entry-pane end of the lore brainstorm review (ADR-0046 slice 3), as a
// per-instance rune controller — the shape `LoreScrubController` /
// `SnapshotStripController` use, and NodeEditor already composes.
//
// A `revise:entry` brainstorm (launched from LoreBrainstormBar) commits an
// `EntryPatch` into the `loreBrainstorm` cross-pane store. This controller
// derives the proposed-vs-current flips for the open lore entry — the body plus
// each changed `long_text` field (slice 3a; slice 3b grows `fields` to the
// structured field types) — and **owns the review as a transaction** (#634).
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
import type { DocumentKind, EntryMetadata, MetadataSchema } from "@/lib/types";
import type { FieldFlip } from "@/lib/utils/loreRevision";
import { loreBrainstorm } from "@/lib/stores/loreBrainstorm.svelte";

export class LoreProposalController {
  // Fed by the host each render — the derivations below track these.
  documentKind = $state<DocumentKind>("scene");
  sceneId = $state<string | null>(null);
  schema = $state<MetadataSchema | null>(null);
  metadata = $state<EntryMetadata>({});

  // Wired by the host — the write side of a commit (see the module note).
  onAdoptFields: ((fields: Record<string, string>) => void) | null = null;
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

  /** The patch committed for the open lore entry, or null. Gated on lore. */
  proposal = $derived(
    this.documentKind === "lore" && this.sceneId
      ? loreBrainstorm.proposalFor(this.sceneId)
      : null,
  );

  /** The `long_text` fields the patch proposes, paired with their current value —
   *  each reviewed as its own run-diff flip. Structured fields in the patch are
   *  ignored here (slice 3b renders those); the body is handled separately. */
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

  /** Something to review only when the patch touches the body or a `long_text`
   *  field. (An all-structured patch reaches here empty in slice 3a; ChatBodyView
   *  already told the author nothing renders yet.) */
  hasReview = $derived(
    !!this.proposal && (this.proposal.body != null || this.fields.length > 0),
  );

  // ---- review-local resolution (the accumulation, never a write) -------------
  //
  // The running "take proposed here" decision per reviewable unit. The body key
  // is separate from field ids so a field literally named "body" can't collide.
  // `null` means "unchanged from current" (declined / not yet touched). These
  // never touch `metadata`, so the frozen diff cannot drift as the author works.
  resolvedBody = $state<string | null>(null);
  resolvedText = $state<Record<string, string | null>>({});

  /** A body flip reports its running resolution (null while unchanged). */
  setBodyResolution(value: string | null): void {
    this.resolvedBody = value;
  }

  /** A `long_text` field flip reports its running resolution (null while
   *  unchanged). */
  setFieldResolution(fieldId: string, value: string | null): void {
    this.resolvedText = { ...this.resolvedText, [fieldId]: value };
  }

  /** Whether the author has adopted anything — the "you have changes" signal the
   *  close guard reads to decide between a silent discard and the Save prompt. */
  hasPendingChanges = $derived(
    this.resolvedBody !== null || Object.values(this.resolvedText).some((v) => v !== null),
  );

  /** Drop the accumulated resolution. Called on commit/abandon and by the host
   *  whenever the proposal identity changes, so a superseding commit starts
   *  clean instead of inheriting the previous review's adoptions. */
  resetResolution(): void {
    this.resolvedBody = null;
    this.resolvedText = {};
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
   *  body + metadata land in a single lore PUT (ADR-0046 §1). A commit with
   *  nothing adopted is a plain dismiss (no write), exactly like "Close". */
  async commit(): Promise<boolean> {
    const fields: Record<string, string> = {};
    for (const [fieldId, value] of Object.entries(this.resolvedText)) {
      if (value !== null) fields[fieldId] = value;
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

  /** Dismiss the proposal for the open entry. Low-level: prefer commit/abandon,
   *  which also clear the resolution. */
  clear(): void {
    if (this.sceneId) loreBrainstorm.clear(this.sceneId);
  }
}
