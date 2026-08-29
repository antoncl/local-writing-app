<script lang="ts">
  // The "changed on disk" diff-preview modal (ADR-0077 rung 3, #1638).
  // confirmService's dialog (ConfirmModal) is text-only; this is its
  // rich-content sibling — it composes the same Modal chrome but renders the
  // local-vs-on-disk body as a run-diff instead of a fixed message, so the
  // author sees what actually differs before choosing a resolution.
  import Modal from "@/components/dialogs/Modal.svelte";
  import ReadOnlyBodyOverlay from "@/components/editor/body/ReadOnlyBodyOverlay.svelte";
  import { reviewBodyProposal } from "@/lib/utils/entryRevision";
  import { renderDiffRuns } from "@/lib/utils/diffRuns";
  import { bodiesEqual } from "@/lib/editor-core/editorPaneModel";
  import { conflictDiffService, type ConflictDiffAction } from "@/lib/stores/conflictDiffService.svelte";

  const req = $derived(conflictDiffService.active);

  // Only diff when both sides are known bodies that actually differ (ignoring
  // trailing whitespace, same normalization the autosave dirty-check uses) —
  // otherwise the conflict is field-only and there is nothing to flip.
  const hasBodyDiff = $derived(
    !!req && req.localBody != null && req.onDiskBody != null && !bodiesEqual(req.localBody, req.onDiskBody),
  );

  // Same effect pattern as RevisionFlip: local body is the warm "now" side,
  // on-disk body the cool "was" side (reviewBodyProposal(current, proposed)).
  let html = $state("");
  $effect(() => {
    const current = req;
    if (!current || !hasBodyDiff || current.localBody == null || current.onDiskBody == null) {
      html = "";
      return;
    }
    const runs = reviewBodyProposal(current.localBody, current.onDiskBody).runs;
    let cancelled = false;
    void renderDiffRuns(runs, "both").then((rendered) => {
      if (!cancelled) html = rendered;
    });
    return () => {
      cancelled = true;
    };
  });

  function choose(action: ConflictDiffAction): void {
    conflictDiffService.select(action);
  }
</script>

{#if req}
  <Modal
    title={req.title}
    frameStyle="--modal-width: min(680px, calc(100vw - 48px)); --modal-max-height: 80vh; --modal-overflow-y: auto;"
  >
    <p>
      This document was edited somewhere else while you had unsaved changes. Here's what differs — pick which
      version to keep.
    </p>
    {#if hasBodyDiff}
      <div class="conflict-diff-body">
        <ReadOnlyBodyOverlay {html} label="Conflict preview" tone="snapshot" />
      </div>
      <div class="conflict-diff-legend">
        <span class="conflict-diff-swatch conflict-diff-swatch-now" aria-hidden="true"></span>
        <span>your version</span>
        <span class="conflict-diff-swatch conflict-diff-swatch-was" aria-hidden="true"></span>
        <span>on disk</span>
      </div>
    {:else if req.localBody != null && req.onDiskBody != null}
      <p>The text is identical — the change is in the document's fields (status, metadata).</p>
    {:else}
      <p>The on-disk version couldn't be loaded to compare — choose carefully.</p>
    {/if}
    {#snippet actions()}
      {#each req.actions as action, i (action.label)}
        <button
          type="button"
          class:danger-primary={action.destructive}
          class:primary={!action.destructive && i === req.actions.length - 1}
          onclick={() => choose(action)}
        >
          {action.label}
        </button>
      {/each}
    {/snippet}
  </Modal>
{/if}

<style>
  .conflict-diff-body {
    max-height: 48vh;
    overflow: auto;
    border: 1px solid var(--divider);
    border-radius: 6px;
  }

  .conflict-diff-legend {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  .conflict-diff-swatch {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: var(--r-sm);
  }

  .conflict-diff-swatch-now {
    background: var(--diff-now);
  }

  .conflict-diff-swatch-was {
    background: var(--diff-was);
    margin-left: 10px;
  }
</style>
