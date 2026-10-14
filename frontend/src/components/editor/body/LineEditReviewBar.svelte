<!--
  LineEditReviewBar (#2460) - the review controls for a Line edit's pending
  edits, pinned to the bottom of the editor pane. It is the last child of the
  scroll frame and sticky, so it sits in the flow after the text (the last lines
  are never under it) and stays at the pane's bottom edge while you read.

  Pure presentation: the host (AiSuggestionController) owns the state and the
  actions. mousedown preventDefault keeps the editor focused; the action runs on
  click, so the keyboard (Tab, Enter) works too. The same actions are on
  Alt+Arrow / Alt+Enter / Alt+Backspace in the editor.
-->
<script lang="ts">
  import { formatCostEur } from "@/lib/utils/money";
  import type { AiSuggestionMeta } from "@/lib/editor-core/aiToolbar";

  interface Props {
    lineEdits: { remaining: number; index: number; currentReason: string } | null;
    meta: AiSuggestionMeta | null;
    generating?: boolean;
    onPrev: () => void;
    onNext: () => void;
    onAccept: () => void;
    onReject: () => void;
    onAcceptAll: () => void;
    onRejectAll: () => void;
    onRetry: () => void;
  }

  let {
    lineEdits, meta, generating = false,
    onPrev, onNext, onAccept, onReject, onAcceptAll, onRejectAll, onRetry,
  }: Props = $props();

  const keepFocus = (e: MouseEvent) => e.preventDefault();
</script>

{#if lineEdits}
  <div class="line-edit-review-bar" data-testid="line-edit-review-bar" role="toolbar" aria-label="Review line edits">
    <span class="ler-count" data-testid="line-edit-count">Edit {lineEdits.index} of {lineEdits.remaining}</span>
    <button type="button" class="ler-btn" data-testid="line-edit-prev" aria-label="Previous edit" title="Previous edit (Alt+Up)" onmousedown={keepFocus} onclick={onPrev}>‹</button>
    <button type="button" class="ler-btn" data-testid="line-edit-next" aria-label="Next edit" title="Next edit (Alt+Down)" onmousedown={keepFocus} onclick={onNext}>›</button>
    <span class="ler-reason" data-testid="line-edit-reason" title={lineEdits.currentReason}>{lineEdits.currentReason}</span>
    <button type="button" class="ler-btn ler-accept" data-testid="line-edit-accept" title="Accept this edit (Alt+Enter)" onmousedown={keepFocus} onclick={onAccept}>Accept</button>
    <button type="button" class="ler-btn ler-reject" data-testid="line-edit-reject" title="Reject this edit (Alt+Backspace)" onmousedown={keepFocus} onclick={onReject}>Reject</button>
    <button type="button" class="ler-btn" data-testid="line-edit-accept-all" title="Accept every remaining edit" onmousedown={keepFocus} onclick={onAcceptAll}>Accept all</button>
    <button type="button" class="ler-btn" data-testid="line-edit-reject-all" title="Reject every remaining edit" onmousedown={keepFocus} onclick={onRejectAll}>Reject all</button>
    <button type="button" class="ler-btn" data-testid="line-edit-retry" title="Drop what is left and ask again on the same text" disabled={generating} onmousedown={keepFocus} onclick={onRetry}>Retry</button>
    {#if meta}
      <span class="ler-meta" data-testid="line-edit-meta">
        {meta.model}{#if meta.cost_usd != null} · {formatCostEur(meta.cost_usd)}{/if}
      </span>
    {/if}
  </div>
{/if}

<style>
  .line-edit-review-bar {
    position: sticky;
    bottom: 0;
    z-index: 20;
    flex: none;
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 6px 12px;
    background: var(--surface);
    border-top: 1px solid var(--divider);
    font-size: var(--fs-sm);
    color: var(--text-2);
    cursor: default;
    user-select: none;
  }

  .ler-count {
    flex: none;
    font-weight: 500;
    color: var(--text);
    padding-right: 4px;
  }

  .ler-reason {
    flex: 1 1 0;
    min-width: 0;
    padding: 0 8px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-2);
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

  .ler-accept {
    color: var(--accent);
    font-weight: 500;
  }

  .ler-reject {
    color: var(--danger);
  }

  .ler-meta {
    flex: none;
    padding-left: 8px;
    font-size: var(--fs-xs);
    color: var(--text-3);
    white-space: nowrap;
  }
</style>
