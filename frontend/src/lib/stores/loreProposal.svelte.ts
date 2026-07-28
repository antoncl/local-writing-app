// The entry-pane end of the lore brainstorm review (ADR-0046 slice 3), as a
// per-instance rune controller — the shape `LoreScrubController` /
// `SnapshotStripController` use, and NodeEditor already composes.
//
// A `revise:entry` brainstorm (launched from LoreBrainstormBar) commits an
// `EntryPatch` into the `loreBrainstorm` cross-pane store. This controller
// derives the proposed-vs-current flips for the open lore entry — the body plus
// each changed `long_text` field (slice 3a; slice 3b grows `fields` to the
// structured field types). The host feeds it each render (documentKind /
// sceneId / schema / the live metadata buffer) and renders `fields` + `hasReview`.
//
// **Adopting is the host's job**, exactly as `SnapshotStripController.onAdopt`
// is: the controller decides only WHAT the patch touches, never writes it. The
// host merges the fields into its own metadata state and adopts the body through
// its prose buffer, so both feed the same autosave and body + metadata coalesce
// into a single lore PUT (no bespoke endpoint, ADR-0046 §1).
import type { DocumentKind, EntryMetadata, MetadataSchema } from "@/lib/types";
import type { FieldFlip } from "@/lib/utils/loreRevision";
import { loreBrainstorm } from "@/lib/stores/loreBrainstorm.svelte";

export class LoreProposalController {
  // Fed by the host each render — the derivations below track these.
  documentKind = $state<DocumentKind>("scene");
  sceneId = $state<string | null>(null);
  schema = $state<MetadataSchema | null>(null);
  metadata = $state<EntryMetadata>({});

  // Wired by the host — the write side of an adopt (see the module note).
  onAdoptFields: ((fields: Record<string, string>) => void) | null = null;
  onAdoptBody: ((body: string) => void | Promise<void>) | null = null;
  onEmitChange: (() => void) | null = null;
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

  /** Adopt the reviewed patch in ONE save: merge adopted field values into the
   *  host's metadata, then adopt the body through its buffer — both feed the same
   *  autosave, so body + metadata coalesce into a single lore PUT (ADR-0046 §1).
   *  A body-less patch still flushes the fields. */
  async adopt(body: string | null, fields: Record<string, string>): Promise<void> {
    const hasFields = Object.keys(fields).length > 0;
    if (hasFields) this.onAdoptFields?.(fields);
    if (body != null) {
      await this.onAdoptBody?.(body);
    } else if (hasFields) {
      this.onEmitChange?.();
    }
  }

  /** The body the author currently sees (live buffer, not the saved file) — the
   *  side the body flip compares against, buffer-safe like the snapshot compare. */
  currentBody(): string {
    return this.readCurrentBody?.() ?? "";
  }

  /** Dismiss the proposal for the open entry (Discard, or after adopt). */
  clear(): void {
    if (this.sceneId) loreBrainstorm.clear(this.sceneId);
  }
}
