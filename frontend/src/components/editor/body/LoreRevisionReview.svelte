<script lang="ts">
  // The proposed-vs-current review for a lore brainstorm commit (ADR-0046
  // slice 2/3). A `revise:entry` chat finalises and the server validates its
  // reply into an EntryPatch; the author reviews it against the entry's current
  // state as the same flip the snapshot compare uses, and adopts region by
  // region — across the body AND each changed long_text field (slice 3a).
  //
  // Deliberately the snapshot-adopt shape, not a second write path: on Done the
  // resolved body and field values are handed back through `onAdopt`, which the
  // entry pane writes via the SAME emitChange autosave a manual body/field edit
  // uses — body and metadata coalesce into one PUT (ADR-0046 §1; no bespoke
  // endpoint). Nothing is written during review; Discard is a true no-op.

  import RevisionFlip from "@/components/editor/body/RevisionFlip.svelte";
  import type { FieldFlip } from "@/lib/utils/loreRevision";

  let {
    currentBody,
    proposedBody,
    fields,
    onAdopt,
    onClose,
  }: {
    /** The entry's body as the author currently sees it (the live buffer). */
    currentBody: string;
    /** The committed revised body, or null when the patch changes no body. */
    proposedBody: string | null;
    /** The long_text fields the patch proposes, each reviewed as its own flip. */
    fields: FieldFlip[];
    /** Write the resolved body + field values once, on Done. `body` is null
     *  when the body was not part of the patch or was left unchanged. */
    onAdopt: (body: string | null, fields: Record<string, string>) => void;
    /** Dismiss the review (clear the pending proposal). */
    onClose: () => void;
  } = $props();

  // Each flip reports its running resolution here (null while unchanged). The
  // body key is separate from field ids so a field literally named "body" can't
  // collide.
  let resolvedBody = $state<string | null>(null);
  let resolvedFields = $state<Record<string, string | null>>({});

  let changesRemain = $derived(
    resolvedBody !== null || Object.values(resolvedFields).some((v) => v !== null),
  );

  function done(): void {
    const adoptedFields: Record<string, string> = {};
    for (const [fieldId, value] of Object.entries(resolvedFields)) {
      if (value !== null) adoptedFields[fieldId] = value;
    }
    onAdopt(resolvedBody, adoptedFields);
    onClose();
  }

  function discard(): void {
    // Nothing was written during review, so discarding is just dismissal.
    onClose();
  }
</script>

<div class="lore-revision-review">
  <div class="review-bar">
    <span class="review-hint">
      Proposed revision — click the <span class="was-swatch">dotted</span> wording to adopt it.
    </span>
    <div class="review-actions">
      <button type="button" class="review-discard" onclick={discard}>Discard</button>
      <button type="button" class="review-done" onclick={done}>
        {changesRemain ? "Done" : "Close"}
      </button>
    </div>
  </div>
  <div class="review-flips">
    {#if proposedBody !== null}
      <RevisionFlip
        currentText={currentBody}
        proposedText={proposedBody}
        label="Body"
        onResolved={(v) => (resolvedBody = v)}
      />
    {/if}
    {#each fields as field (field.fieldId)}
      <RevisionFlip
        currentText={field.currentValue}
        proposedText={field.proposedValue}
        label={field.label}
        onResolved={(v) => (resolvedFields = { ...resolvedFields, [field.fieldId]: v })}
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
