<script lang="ts">
  // The proposed-vs-current review for a lore brainstorm commit (ADR-0046
  // slice 2/3). A `revise:entry` chat finalises and the server validates its
  // reply into an EntryPatch; the author reviews it against the entry's current
  // state as the same flip the snapshot compare uses, and adopts region by
  // region — across the body AND each changed long_text field (slice 3a).
  //
  // This is a pure render + gesture surface. The review is a frozen transaction
  // whose state lives in `LoreProposalController` (#634): each flip PUSHES its
  // running resolution to the controller via `onBodyResolved`/`onFieldResolved`
  // (never a local write), Done fires `onDone` (the controller's single explicit
  // PUT — body + metadata in one write, ADR-0046 §1), and Discard fires
  // `onDiscard`. The controller owns the accumulation so the pane's close guard
  // can commit the same pending changes. Nothing is written during review.

  import RevisionFlip from "@/components/editor/body/RevisionFlip.svelte";
  import type { FieldFlip } from "@/lib/utils/loreRevision";

  let {
    currentBody,
    proposedBody,
    fields,
    hasChanges,
    onBodyResolved,
    onFieldResolved,
    onDone,
    onDiscard,
  }: {
    /** The entry's body as the author currently sees it (the live buffer). */
    currentBody: string;
    /** The committed revised body, or null when the patch changes no body. */
    proposedBody: string | null;
    /** The long_text fields the patch proposes, each reviewed as its own flip. */
    fields: FieldFlip[];
    /** Whether the author has adopted anything yet — drives the Done/Close label.
     *  Owned by the controller (the close guard reads the same signal). */
    hasChanges: boolean;
    /** Push the body flip's running resolution to the controller (null while
     *  unchanged from current). The controller accumulates; nothing writes here. */
    onBodyResolved: (value: string | null) => void;
    /** Push a long_text field flip's running resolution to the controller. */
    onFieldResolved: (fieldId: string, value: string | null) => void;
    /** The save gesture: commit the accumulated patch as one PUT. */
    onDone: () => void;
    /** Discard the proposal without writing (the entry was frozen). */
    onDiscard: () => void;
  } = $props();
</script>

<div class="lore-revision-review">
  <div class="review-bar">
    <span class="review-hint">
      Proposed revision — click the <span class="was-swatch">dotted</span> wording to adopt it.
    </span>
    <div class="review-actions">
      <button type="button" class="review-discard" onclick={onDiscard}>Discard</button>
      <button type="button" class="review-done" onclick={onDone}>
        {hasChanges ? "Done" : "Close"}
      </button>
    </div>
  </div>
  <div class="review-flips">
    {#if proposedBody !== null}
      <RevisionFlip
        currentText={currentBody}
        proposedText={proposedBody}
        label="Body"
        onResolved={(v) => onBodyResolved(v)}
      />
    {/if}
    {#each fields as field (field.fieldId)}
      <RevisionFlip
        currentText={field.currentValue}
        proposedText={field.proposedValue}
        label={field.label}
        onResolved={(v) => onFieldResolved(field.fieldId, v)}
      />
    {/each}
  </div>
</div>

<style>
  .lore-revision-review {
    display: flex;
    flex-direction: column;
    min-height: 0;
    flex: 1;
  }
  .review-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 6px 24px;
    border-bottom: 1px solid color-mix(in srgb, var(--diff-was) 30%, transparent);
    background: color-mix(in srgb, var(--diff-was) 8%, transparent);
  }
  .review-hint {
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .was-swatch {
    color: var(--diff-was);
    font-weight: 600;
  }
  .review-actions {
    display: flex;
    gap: 8px;
  }
  .review-actions button {
    font: inherit;
    font-size: var(--fs-sm);
    padding: 3px 12px;
    border-radius: var(--r-sm);
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
  }
  .review-actions button:hover {
    background: var(--inset);
  }
  .review-done {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
  }
  .review-flips {
    display: flex;
    flex-direction: column;
    min-height: 0;
    flex: 1;
    overflow-y: auto;
  }
</style>
