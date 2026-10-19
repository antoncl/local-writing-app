<!--
  LineEditReviewBar (#2460) - the review controls for a Line edit's pending
  edits - the batch controls only; the current edit's own Accept / Reject /
  prev / next / reason are a card beside the edit (editor-core/lineEditCard.ts).
  NodeEditor mounts it as a footer row of the editor pane, between the
  foot dock and the status line - OUTSIDE the scroll frame, so the frame just
  gets shorter while it is shown and the bar never covers text. In a narrow
  pane its groups wrap onto a second row instead of clipping.

  Pure presentation: the host (AiSuggestionController) owns the state and the
  actions. mousedown preventDefault keeps the editor focused; the action runs on
  click, so the keyboard (Tab, Enter) works too. The same actions are on
  Alt+Arrow / Alt+Enter / Alt+Backspace in the editor.
-->
<script lang="ts">
  import { formatCostEur } from "@/lib/utils/money";
  import type { AiSuggestionMeta } from "@/lib/editor-core/aiToolbar";
  import type { ReviewView } from "@/lib/editor-core/lineEditSuggestions";
  import ReviewViewToggle from "@/components/editor/body/ReviewViewToggle.svelte";

  interface Props {
    lineEdits: { remaining: number; index: number } | null;
    meta: AiSuggestionMeta | null;
    generating?: boolean;
    onAcceptAll: () => void;
    onRejectAll: () => void;
    onRetry: () => void;
    /** The version the passages read as (#2561); the toggle shows with `onView`. */
    view?: ReviewView;
    onView?: (view: ReviewView) => void;
  }

  let {
    lineEdits, meta, generating = false,
    onAcceptAll, onRejectAll, onRetry,
    view = "both", onView,
  }: Props = $props();

  const keepFocus = (e: MouseEvent) => e.preventDefault();
</script>

{#if lineEdits}
  <div class="line-edit-review-bar" data-testid="line-edit-review-bar" role="toolbar" aria-label="Review line edits">
    <span class="ler-group">
      <span class="ler-count" data-testid="line-edit-count">Edit {lineEdits.index} of {lineEdits.remaining}</span>
    </span>
    <span class="ler-group">
      <button type="button" class="ler-btn" data-testid="line-edit-accept-all" title="Accept every remaining edit" onmousedown={keepFocus} onclick={onAcceptAll}>Accept all</button>
      <button type="button" class="ler-btn" data-testid="line-edit-reject-all" title="Reject every remaining edit" onmousedown={keepFocus} onclick={onRejectAll}>Reject all</button>
      <button type="button" class="ler-btn" data-testid="line-edit-retry" title="Drop what is left and ask again on the same text" disabled={generating} onmousedown={keepFocus} onclick={onRetry}>Retry</button>
    </span>
    {#if onView}<ReviewViewToggle {view} {onView} />{/if}
    {#if meta}
      <span class="ler-meta" data-testid="line-edit-meta">
        {meta.model}{#if meta.cost_usd != null} · {formatCostEur(meta.cost_usd)}{/if}
      </span>
    {/if}
  </div>
{/if}

<style>
  .line-edit-review-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 2px 4px;
    padding: 6px 12px;
    background: var(--surface);
    border-top: 1px solid var(--divider);
    font-size: var(--fs-sm);
    color: var(--text-2);
    cursor: default;
    user-select: none;
  }

  .ler-group {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .ler-count {
    flex: none;
    font-weight: 500;
    color: var(--text);
    padding-right: 4px;
  }

  .ler-btn {
    flex: none;
    background: transparent;
    border: none;
    color: var(--text-2);
    padding: 4px 8px;
    font-size: var(--fs-sm);
    line-height: 1;
    border-radius: 4px;
    cursor: pointer;
  }

  .ler-btn:hover:not(:disabled) {
    background: var(--inset);
    color: var(--text);
  }

  .ler-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .ler-meta {
    flex: none;
    padding-left: 8px;
    font-size: var(--fs-xs);
    color: var(--text-3);
    white-space: nowrap;
  }
</style>
