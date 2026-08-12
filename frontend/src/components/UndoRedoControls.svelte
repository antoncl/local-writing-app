<!--
  UndoRedoControls — the shared visible undo/redo affordance for node-canvas
  surfaces (ADR-0050 §7). A node canvas doesn't telegraph Ctrl+Z the way a text
  field does, so the control is visible, and it is the a11y story a bare
  keybinding can't tell: named buttons, disabled when idle (bound to the
  caretaker's canUndo/canRedo), a non-chord target, and an aria-live region that
  announces what just reversed. First the view designer's, generalized in S7c
  (#760) when the plot board became the second surface.

  Positioning is the host's job — the toolbar decides where the cluster sits
  (§7 leaves placement to implementation); this only renders the buttons and the
  announcer.
-->
<script lang="ts">
  let {
    canUndo,
    canRedo,
    undoTitle,
    redoTitle,
    announcement,
    onUndo,
    onRedo,
    scope,
  }: {
    canUndo: boolean;
    canRedo: boolean;
    undoTitle: string;
    redoTitle: string;
    announcement: string;
    onUndo: () => void;
    onRedo: () => void;
    // Optional scope word folded into the button aria-labels + group label, so a
    // screen reader hears e.g. "Undo layout" where the history is narrower than the
    // whole surface (#860). Omitted → the plain "Undo"/"Redo"/"History".
    scope?: string;
  } = $props();
  let undoLabel = $derived(scope ? `Undo ${scope}` : "Undo");
  let redoLabel = $derived(scope ? `Redo ${scope}` : "Redo");
  let groupLabel = $derived(scope ? `${scope} history` : "History");
</script>

<div class="undo-cluster" role="group" aria-label={groupLabel}>
  <button type="button" class="undo-btn" disabled={!canUndo} aria-label={undoLabel} title={undoTitle} onclick={onUndo}
    ><i class="ti ti-arrow-back-up" aria-hidden="true"></i></button>
  <button type="button" class="undo-btn" disabled={!canRedo} aria-label={redoLabel} title={redoTitle} onclick={onRedo}
    ><i class="ti ti-arrow-forward-up" aria-hidden="true"></i></button>
</div>
<!-- What just reversed, for screen readers (§7): "Undid delete node". -->
<span class="sr-only" aria-live="polite">{announcement}</span>

<style>
  .undo-cluster {
    display: flex;
    gap: var(--sp-1);
  }
  .undo-btn {
    border: none;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-md);
    line-height: 1;
    cursor: pointer;
    padding: var(--sp-1);
    border-radius: var(--r-sm);
  }
  .undo-btn:hover:not(:disabled) {
    color: var(--text);
    background: var(--inset);
  }
  .undo-btn:disabled {
    opacity: 0.35;
    cursor: default;
  }
  /* .sr-only (the aria-live announcer) is the shared utility in styles.css. */
</style>
