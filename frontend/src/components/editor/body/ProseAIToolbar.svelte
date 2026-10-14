<!--
  ProseAIToolbar — floating inline toolbar shown over an AI continuation/revision
  in ProseBodyView. Pure presentation: it shows the generating spinner, an error
  with a Dismiss, or the accept/retry/discard controls + usage-cost meta for a
  ready suggestion.

  The host (the AI-suggestion pipeline) owns ALL state — when/where it shows
  (position), generating/suggestionId/error/meta — and the accept/retry/discard/
  dismiss actions. onmousedown handlers preventDefault inline so a click never
  blurs the editor.
-->
<script lang="ts">
  import { formatCostEur } from "@/lib/utils/money";
  import type { AiSuggestionMeta, AiToolbarPosition } from "@/lib/editor-core/aiToolbar";

  interface Props {
    position: AiToolbarPosition;
    generating: boolean;
    suggestionId: string | null;
    error: string | null;
    meta: AiSuggestionMeta | null;
    // Pending line edits (#2460): the toolbar then offers Accept all / Reject all.
    lineEdits?: { remaining: number } | null;
    onAcceptAll?: () => void;
    onRejectAll?: () => void;
    onAccept: () => void;
    onRetry: () => void;
    onDiscard: () => void;
    onDismissError: () => void;
  }

  let {
    position, generating, suggestionId, error, meta, lineEdits = null,
    onAcceptAll, onRejectAll, onAccept, onRetry, onDiscard, onDismissError,
  }: Props = $props();
</script>

{#if position.visible && (generating || suggestionId || lineEdits || error)}
  <div
    class="ai-inline-toolbar"
    class:ai-inline-toolbar-loading={generating}
    class:ai-inline-toolbar-error={error && !suggestionId && !lineEdits}
    class:ai-inline-toolbar-below={position.placement === "below"}
    style={`left: ${position.x}px; top: ${position.y}px;`}
  >
    {#if generating}
      <span class="ai-toolbar-spinner" aria-hidden="true">⟳</span>
      <span class="ai-toolbar-status">Generating…</span>
    {:else if error && !suggestionId && !lineEdits}
      <span class="ai-toolbar-status">⚠ {error}</span>
      <button type="button" class="ai-toolbar-btn" onmousedown={(e) => { e.preventDefault(); onDismissError(); }} title="Dismiss">
        Dismiss
      </button>
    {:else if suggestionId || lineEdits}
      {#if lineEdits}
        <button type="button" class="ai-toolbar-btn ai-toolbar-accept" data-testid="line-edit-accept-all" onmousedown={(e) => { e.preventDefault(); onAcceptAll?.(); }} title="Accept every remaining edit">
          Accept all ({lineEdits.remaining})
        </button>
      {:else}
        <button type="button" class="ai-toolbar-btn ai-toolbar-accept" onmousedown={(e) => { e.preventDefault(); onAccept(); }} title="Accept (keep the text)">
          Accept
        </button>
      {/if}
      <button type="button" class="ai-toolbar-btn" onmousedown={(e) => { e.preventDefault(); onRetry(); }} title="Retry (regenerate)" disabled={generating}>
        Retry
      </button>
      {#if lineEdits}
        <button type="button" class="ai-toolbar-btn ai-toolbar-discard" data-testid="line-edit-reject-all" onmousedown={(e) => { e.preventDefault(); onRejectAll?.(); }} title="Reject every remaining edit">
          Reject all
        </button>
      {:else}
        <button type="button" class="ai-toolbar-btn ai-toolbar-discard" onmousedown={(e) => { e.preventDefault(); onDiscard(); }} title="Discard (delete the text)">
          Discard
        </button>
      {/if}
      {#if meta}
        <span class="ai-toolbar-meta">
          {#if !lineEdits}{meta.wordCount} words, {/if}{meta.model}{#if meta.truncated} · truncated{/if}
          {#if meta.usage}
            {@const u = meta.usage}
            {@const totalIn = u.input_tokens + u.cached_input_tokens + u.cache_write_tokens}
            {@const cachePct = totalIn > 0 ? Math.round((u.cached_input_tokens / totalIn) * 100) : 0}
            <span class="ai-toolbar-meta-sep" title={`Input: ${totalIn} tok (${u.cached_input_tokens} cached, ${u.cache_write_tokens} written). Output: ${u.output_tokens} tok.`}>
              · {totalIn} → {u.output_tokens} tok{#if cachePct > 0} · {cachePct}% cached{/if}
            </span>
          {/if}
          {#if meta.cost_usd != null}
            <span class="ai-toolbar-meta-cost">· {formatCostEur(meta.cost_usd)}</span>
          {/if}
        </span>
      {/if}
    {/if}
  </div>
{/if}

<style>
  .ai-inline-toolbar {
    position: absolute;
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 4px 6px;
    background: var(--toolbar-surface);
    border-radius: 6px;
    font-size: var(--fs-sm);
    color: var(--toolbar-text);
    box-shadow: var(--elev-2);
    z-index: 30;
    white-space: nowrap;
    user-select: none;
    /* `top` anchors at the suggestion's first-line top; lift the toolbar fully
       clear of that line so it never occludes the generated prose (#1275). */
    transform: translateY(calc(-100% - 4px));
  }

  /* Flip: `top` anchors at the first line's BOTTOM (set by the controller when
     there's no room above), so drop the toolbar just under it. */
  .ai-inline-toolbar-below {
    transform: translateY(4px);
  }

  .ai-toolbar-btn {
    background: transparent;
    border: none;
    color: inherit;
    padding: 4px 9px;
    font-size: var(--fs-sm);
    font-weight: 500;
    cursor: pointer;
    border-radius: 4px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    line-height: 1;
  }

  .ai-toolbar-btn:hover {
    background: var(--toolbar-hover);
  }

  .ai-toolbar-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .ai-toolbar-accept {
    /* Light mint on the dark ai inline toolbar — correct in both themes
       (the toolbar surface never flips); part of the --toolbar-* glass family. */
    color: var(--toolbar-accent);
  }

  /* The toolbar surface never flips with the theme, so its text takes the
     --toolbar-* family, never a theme token — a theme *border* token goes dark
     in dark mode and vanishes on this surface (#2430). */
  .ai-toolbar-discard {
    color: var(--toolbar-danger-text);
  }

  .ai-toolbar-meta {
    padding: 0 8px 0 6px;
    color: var(--toolbar-text-muted);
    font-style: italic;
    border-left: 1px solid var(--toolbar-divider);
    margin-left: 2px;
  }

  .ai-toolbar-status {
    padding: 2px 8px;
    font-style: italic;
  }

  .ai-toolbar-spinner {
    display: inline-block;
    padding-left: 6px;
    animation: ai-spin 1.1s linear infinite;
    transform-origin: center;
    font-size: var(--fs-md);
    line-height: 1;
  }

  @keyframes ai-spin {
    to { transform: rotate(360deg); }
  }

  .ai-inline-toolbar-loading {
    background: var(--toolbar-loading);
  }

  .ai-inline-toolbar-error {
    background: var(--toolbar-error);
  }

  .ai-inline-toolbar-error .ai-toolbar-status {
    /* Light pink on the dark error toolbar — intentional in both themes;
       part of the --toolbar-* glass family. */
    color: var(--toolbar-danger-text);
    font-style: normal;
  }
</style>
