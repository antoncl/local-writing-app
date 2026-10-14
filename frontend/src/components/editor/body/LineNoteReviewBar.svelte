<!--
  LineNoteReviewBar (ADR-0098) - the review controls for a lore check's pending
  notes: the batch controls only; the current note's own Open entry / Dismiss /
  prev / next are a card beside the quote (editor-core/lineNoteCard.ts). A pane
  footer row like LineEditReviewBar, OUTSIDE the scroll frame, so it never covers
  text. It also names what the check ran against - the lore entries sent to the
  model - because "no contradictions" only means something for those.

  Pure presentation: the host (AiSuggestionController) owns the state and the
  actions. mousedown preventDefault keeps the editor focused.
-->
<script lang="ts">
  import { formatCostEur } from "@/lib/utils/money";
  import type { AiSuggestionMeta } from "@/lib/editor-core/aiToolbar";
  import type { CheckedEntry } from "@/lib/types";

  interface Props {
    lineNotes: { remaining: number; index: number; checkedAgainst: CheckedEntry[] } | null;
    meta: AiSuggestionMeta | null;
    generating?: boolean;
    onDismissAll: () => void;
    onRetry: () => void;
  }

  let { lineNotes, meta, generating = false, onDismissAll, onRetry }: Props = $props();

  const keepFocus = (e: MouseEvent) => e.preventDefault();
  const checkedNames = $derived((lineNotes?.checkedAgainst ?? []).map((c) => c.name || c.id).join(", "));
</script>

{#if lineNotes}
  <div class="line-note-review-bar" data-testid="line-note-review-bar" role="toolbar" aria-label="Review lore-check notes">
    <span class="lnr-group">
      <span class="lnr-count" data-testid="line-note-count">Note {lineNotes.index} of {lineNotes.remaining}</span>
    </span>
    <span class="lnr-group">
      <button type="button" class="lnr-btn" data-testid="line-note-dismiss-all" title="Dismiss every remaining note" onmousedown={keepFocus} onclick={onDismissAll}>Dismiss all</button>
      <button type="button" class="lnr-btn" data-testid="line-note-retry" title="Drop what is left and check the same text again" disabled={generating} onmousedown={keepFocus} onclick={onRetry}>Retry</button>
    </span>
    {#if meta}
      <span class="lnr-meta" data-testid="line-note-meta">
        {meta.model}{#if meta.cost_usd != null} · {formatCostEur(meta.cost_usd)}{/if}
      </span>
    {/if}
    {#if checkedNames}
      <span class="lnr-checked" data-testid="line-note-checked" title={checkedNames}>Checked against: {checkedNames}</span>
    {/if}
  </div>
{/if}

<style>
  .line-note-review-bar {
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

  .lnr-group {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .lnr-count {
    flex: none;
    font-weight: 500;
    color: var(--text);
    padding-right: 4px;
  }

  .lnr-btn {
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

  .lnr-btn:hover:not(:disabled) {
    background: var(--inset);
    color: var(--text);
  }

  .lnr-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .lnr-meta {
    flex: none;
    padding-left: 8px;
    font-size: var(--fs-xs);
    color: var(--text-3);
    white-space: nowrap;
  }

  /* The checked-against list takes the rest of the row and ellipsizes; the full
     list is the title. In a narrow pane it wraps to its own row. */
  .lnr-checked {
    flex: 1 1 200px;
    min-width: 0;
    padding-left: 8px;
    font-size: var(--fs-xs);
    color: var(--text-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
