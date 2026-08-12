<script lang="ts">
  // The `replace`-mode review for an entry-patch commit (ADR-0051 S5-next). Where
  // EntryRevisionReview shows a per-run adopt flip, this is a plain current→proposed
  // card: a value regenerated from scratch (a scene's `summary` from its prose) has
  // no meaningful run-diff against the old one, so the writer just sees the proposed
  // text and takes it whole or drops it.
  //
  // A pure render + gesture surface, the twin of EntryRevisionReview: the review is
  // a frozen transaction owned by EntryProposalController. `onReplace` accepts the
  // proposed field(s) and commits in one gesture (the controller's single PUT);
  // `onDiscard` drops the proposal without writing. Nothing is written here. The
  // `replace` patch carries no body (stripped at propose time), so a commit only
  // ever writes the field — a scene's prose is never touched.

  import type { FieldFlip } from "@/lib/utils/entryRevision";

  let {
    fields,
    onReplace,
    onDiscard,
  }: {
    /** The field(s) the patch proposes to replace whole — for a scene summary,
     *  exactly one (`summary`), but rendered as a list so the card is generic. */
    fields: FieldFlip[];
    /** Take the proposed value(s) and commit in one gesture. */
    onReplace: () => void;
    /** Drop the proposal without writing (the node was frozen). */
    onDiscard: () => void;
  } = $props();

  // One field is the norm (summary); name it in the bar. More than one falls back
  // to the neutral plural so the card never lies about what it is replacing.
  const heading = $derived(
    fields.length === 1 ? `Proposed ${fields[0].label.toLowerCase()}` : "Proposed changes",
  );
</script>

<div class="replace-review">
  <div class="review-bar">
    <span class="review-hint" title="Replace the current value with the proposed one, or discard it."
      >{heading}</span
    >
    <div class="review-actions">
      <button type="button" class="review-reject" onclick={onDiscard}>Discard</button>
      <button type="button" class="review-replace" onclick={onReplace}>Replace</button>
    </div>
  </div>
  <div class="replace-fields">
    {#each fields as field (field.fieldId)}
      <section class="replace-field">
        {#if fields.length > 1}
          <h4 class="field-label">{field.label}</h4>
        {/if}
        <div class="field-col field-current">
          <span class="col-tag">Current</span>
          <p class="col-text">{field.currentValue || "(empty)"}</p>
        </div>
        <div class="field-col field-proposed">
          <span class="col-tag">Proposed</span>
          <p class="col-text">{field.proposedValue || "(empty)"}</p>
        </div>
      </section>
    {/each}
  </div>
</div>

<style>
  .replace-review {
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
    flex: 1;
    font-size: var(--fs-sm);
    color: var(--text-2);
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
  .review-replace {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
  }
  .replace-fields {
    display: flex;
    flex-direction: column;
    gap: 16px;
    min-height: 0;
    flex: 1;
    overflow-y: auto;
    padding: 16px 24px;
  }
  .replace-field {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .field-label {
    margin: 0;
    font-family: var(--serif);
    font-size: var(--fs-md);
    font-weight: 700;
    color: var(--text);
  }
  .field-col {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 8px 12px;
    border-radius: var(--r-sm);
    border: 1px solid var(--border);
  }
  /* The proposed side takes the cool proposal tint the flip surfaces use, so the
     eye lands on it; the current side is quiet, for reference only. */
  .field-proposed {
    border-color: color-mix(in srgb, var(--diff-was) 40%, transparent);
    background: color-mix(in srgb, var(--diff-was) 8%, transparent);
  }
  .col-tag {
    font-size: var(--fs-xs);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
  }
  .field-current .col-text {
    color: var(--text-2);
  }
  .col-text {
    margin: 0;
    font-size: var(--fs-sm);
    line-height: 1.5;
    white-space: pre-wrap;
    color: var(--text);
  }
</style>
