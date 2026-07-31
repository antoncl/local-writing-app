<script lang="ts">
  // The proposed-vs-current review for an entry-patch brainstorm commit
  // (ADR-0046 slice 2/3; generalized to any schema-typed node, ADR-0048 §5). A
  // `revise:entry` chat finalises and the server validates its reply into an
  // EntryPatch; the author reviews it against the node's current state as the
  // same flip the snapshot compare uses, and adopts region by region — across
  // the body AND each changed long_text field (slice 3a).
  //
  // This is a pure render + gesture surface. The review is a frozen transaction
  // whose state lives in `EntryProposalController` (#634): each flip PUSHES its
  // running resolution to the controller via `onBodyResolved`/`onFieldResolved`
  // (never a local write), Done fires `onDone` (the controller's single explicit
  // PUT — body + metadata in one write, ADR-0046 §1), and Discard fires
  // `onDiscard`. The controller owns the accumulation so the pane's close guard
  // can commit the same pending changes. Nothing is written during review.

  import RevisionFlip from "@/components/editor/body/RevisionFlip.svelte";
  import type { FieldFlip } from "@/lib/utils/entryRevision";
  import type { DiffView } from "@/lib/types";

  let {
    currentBody,
    proposedBody,
    fields,
    hasChanges,
    view,
    onView,
    onBodyResolved,
    onFieldResolved,
    onAcceptAll,
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
    /** Which whole version the prose flips read — the judge axis (#710). */
    view: DiffView;
    /** Switch the judge axis (the segmented control). */
    onView: (view: DiffView) => void;
    /** Push the body flip's running resolution to the controller (null while
     *  unchanged from current). The controller accumulates; nothing writes here. */
    onBodyResolved: (value: string | null) => void;
    /** Push a long_text field flip's running resolution to the controller. */
    onFieldResolved: (fieldId: string, value: string | null) => void;
    /** Take the whole candidate and commit it in one gesture (#710) — the
     *  affirmative half of the whole-version pair; `onDiscard` is the other. */
    onAcceptAll: () => void;
    /** The save gesture: commit the accumulated patch as one PUT. */
    onDone: () => void;
    /** Reject the whole candidate: discard the proposal without writing (the
     *  entry was frozen). The mirror of Accept all. */
    onDiscard: () => void;
  } = $props();

  // The judge axis, worded for a proposal (the snapshot's Active·Snapshot·Both):
  // the current entry (warm `now`), the AI's version (cool `was`), or the diff.
  // Only meaningful when there is prose to read whole; a structured-only patch
  // hides it (the rail already shows both sides of each field).
  const VIEWS: { id: DiffView; label: string; hint: string }[] = [
    { id: "now", label: "Current", hint: "the entry as it is now" },
    { id: "was", label: "Proposed", hint: "the AI's version" },
    { id: "both", label: "Both", hint: "both versions, adjacent" },
  ];
  const hasProse = $derived(proposedBody !== null || fields.length > 0);
</script>

<div class="entry-revision-review">
  <div class="review-bar">
    <span class="review-hint">
      {#if hasProse}
        Proposed revision — read each version whole, or click the <span class="was-swatch">dotted</span> wording to adopt it.
      {:else}
        Proposed revision — adopt the field changes in the details panel.
      {/if}
    </span>
    {#if hasProse}
      <!-- The judge axis: read the current entry or the AI's version whole,
           before deciding (#710). One choice, so a segmented control. -->
      <div class="review-view" role="group" aria-label="Which version">
        {#each VIEWS as option (option.id)}
          <button
            type="button"
            class="rv"
            class:on={view === option.id}
            title={`${option.label} — ${option.hint}`}
            aria-pressed={view === option.id}
            onclick={() => onView(option.id)}>{option.label}</button>
        {/each}
      </div>
    {/if}
    <div class="review-actions">
      <!-- The whole-version pair (#710): take the whole candidate, or keep the
           current entry whole. Reject all IS the frozen-review discard, surfaced
           as Accept all's mirror rather than a separate "Don't save". -->
      <button type="button" class="review-reject" onclick={onDiscard}>Reject all</button>
      <button type="button" class="review-accept" onclick={onAcceptAll}>Accept all</button>
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
        {view}
        onResolved={(v) => onBodyResolved(v)}
      />
    {/if}
    {#each fields as field (field.fieldId)}
      <RevisionFlip
        currentText={field.currentValue}
        proposedText={field.proposedValue}
        label={field.label}
        {view}
        onResolved={(v) => onFieldResolved(field.fieldId, v)}
      />
    {/each}
  </div>
</div>

<style>
  .entry-revision-review {
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
  /* The judge axis (#710). A segmented control, matching the snapshot compare's
     Active·Snapshot·Both: one choice — which version am I reading. */
  .review-view {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    overflow: hidden;
  }
  .rv {
    font: inherit;
    font-size: var(--fs-sm);
    padding: 3px 9px;
    border: 0;
    border-left: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-2);
    cursor: pointer;
    transition: background-color 80ms linear, color 80ms linear;
  }
  .rv:first-child {
    border-left: 0;
  }
  .rv:hover {
    background: var(--inset);
  }
  .rv.on {
    background: var(--accent-soft);
    color: var(--accent-emphasis);
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
