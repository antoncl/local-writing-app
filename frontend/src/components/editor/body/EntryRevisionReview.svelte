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
  import SegmentedControl from "@/components/widgets/SegmentedControl.svelte";
  import type { FieldFlip } from "@/lib/utils/entryRevision";
  import type { DiffView } from "@/lib/types";

  let {
    currentBody,
    proposedBody,
    fields,
    hasChanges,
    view,
    onView,
    onToggleView,
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
    /** Set the judge axis to a specific view (the segmented control, `b` key). */
    onView: (view: DiffView) => void;
    /** Toggle a single whole version against Both (the `a`/`s` keys) — the
     *  controller owns the toggle semantics, exactly like the snapshot strip. */
    onToggleView: (view: "now" | "was") => void;
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
  // A/S/B mirror the snapshot's compare keys. Only meaningful when there is prose
  // to read whole; a structured-only patch hides it (the rail already shows both
  // sides of each field, and the rail follows the view on its own).
  const VIEWS = [
    { id: "now", label: "Current", hint: "the entry as it is now", key: "A", tone: "warm" },
    { id: "was", label: "Proposed", hint: "the AI's version", key: "S", tone: "cool" },
    { id: "both", label: "Both", hint: "both versions, adjacent", key: "B" },
  ] as const;
  const hasProse = $derived(proposedBody !== null || fields.length > 0);

  // A/S/B keys, mirrored from the snapshot strip (SnapshotStrip.onKeydown). The
  // review is a read-only frozen surface, so the letters are free — but only for
  // the pane that owns this review: a review in a hidden tab, or one whose pane
  // does not hold focus, must not answer. Toggle semantics live in the
  // controller (`onToggleView`); auto-repeat is swallowed so a held key does not
  // strobe the view.
  let rootEl: HTMLDivElement | null = $state(null);

  function addressedToThisPane(target: HTMLElement | null): boolean {
    if (!rootEl) return false;
    if (rootEl.closest(".hidden-doc")) return false;
    const pane = rootEl.closest(".editor-panel");
    const focused = target?.closest?.(".editor-panel") ?? null;
    return !focused || !pane || focused === pane;
  }

  function onKeydown(event: KeyboardEvent): void {
    if (!hasProse) return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target as HTMLElement | null;
    if (target?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target?.tagName ?? "")) return;
    if (!/^[asb]$/i.test(event.key)) return;
    if (!addressedToThisPane(target)) return;
    if (event.repeat) {
      event.preventDefault();
      return;
    }
    switch (event.key.toLowerCase()) {
      case "a":
        onToggleView("now");
        break;
      case "s":
        onToggleView("was");
        break;
      case "b":
        onView("both");
        break;
    }
    event.preventDefault();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="entry-revision-review" bind:this={rootEl}>
  <div class="review-bar">
    <!-- A compact label, not a paragraph: the how-to rides the hover title so it
         costs no permanent space (#710 review — screen real estate is scarce). -->
    <span
      class="review-hint"
      title={hasProse
        ? "Read a whole version with Current / Proposed / Both (A / S / B), or click the dotted wording to adopt one part."
        : "Adopt the proposed field changes in the details panel."}
      >Proposed revision</span>
    {#if hasProse}
      <!-- The judge axis: read the current entry or the AI's version whole,
           before deciding (#710). Same control the snapshot compare uses. -->
      <SegmentedControl items={VIEWS} value={view} ariaLabel="Which version" onSelect={onView} />
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
    /* Fill the bar so the judge control + actions group at the right, rather
       than the control floating mid-bar under `space-between` (#710). */
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
