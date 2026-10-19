<!--
  FlagReviewBar (ADR-0100) - the batch controls for flags placed from a
  conversation: one review holding edits and notes together. Styled like
  LineEditReviewBar / LineNoteReviewBar; the current flag's own card (Accept /
  Keep / Reject, prev / next) sits beside it in the prose. Accept all applies the
  edits only; Reject all rejects the edits and dismisses the notes. No Retry (it
  would re-run a selection prompt, which isn't what made these) and no meta line
  (the cost went onto the conversation).

  Pure presentation: the host (AiSuggestionController) owns the state and the
  actions. mousedown preventDefault keeps the editor focused.
-->
<script lang="ts">
  import type { ReviewView } from "@/lib/editor-core/lineEditSuggestions";
  import ReviewViewToggle from "@/components/editor/body/ReviewViewToggle.svelte";

  interface Props {
    flags: { remaining: number; index: number; edits: number } | null;
    onAcceptAllEdits: () => void;
    onRejectAll: () => void;
    /** The version the passages read as (#2561); the toggle shows with `onView`. */
    view?: ReviewView;
    onView?: (view: ReviewView) => void;
  }

  let { flags, onAcceptAllEdits, onRejectAll, view = "both", onView }: Props = $props();

  const keepFocus = (e: MouseEvent) => e.preventDefault();
</script>

{#if flags}
  <div class="flag-review-bar" data-testid="flag-review-bar" role="toolbar" aria-label="Review flags">
    <span class="flr-group">
      <span class="flr-count" data-testid="flag-count">Flag {flags.index} of {flags.remaining}</span>
    </span>
    <span class="flr-group">
      {#if flags.edits > 0}
        <button type="button" class="flr-btn" data-testid="flag-accept-all-edits" title="Accept every remaining edit" onmousedown={keepFocus} onclick={onAcceptAllEdits}>Accept all edits</button>
      {/if}
      <button type="button" class="flr-btn" data-testid="flag-reject-all" title="Reject every remaining edit and dismiss every note" onmousedown={keepFocus} onclick={onRejectAll}>Reject all</button>
    </span>
    {#if onView && flags.edits > 0}<ReviewViewToggle {view} {onView} />{/if}
  </div>
{/if}

<style>
  .flag-review-bar {
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

  .flr-group {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .flr-count {
    flex: none;
    font-weight: 500;
    color: var(--text);
    padding-right: 4px;
  }

  .flr-btn {
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

  .flr-btn:hover {
    background: var(--inset);
    color: var(--text);
  }
</style>
