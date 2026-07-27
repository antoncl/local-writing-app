<!--
  ChatTranscript — presentational message list for ChatBodyView (#99).
  Mostly renders chatHistory; owns only transient copied-button feedback.
  The scroll element is bound back to the parent via `bind:scrollEl` so
  ChatBodyView keeps driving scroll-to-bottom during streaming exactly as before.
-->
<script lang="ts">
  import { onDestroy } from "svelte";
  import { renderChatContent } from "@/lib/utils/chatMessageRender";
  import { formatCostEur } from "@/lib/utils/money";
  import {
    parsePlotSuggestions,
    plotSuggestionClipboardText,
    stripPlotSuggestions,
    type PlotSuggestion,
  } from "@/lib/plotSuggestions";
  import type { ChatMessage } from "@/lib/types";

  interface Props {
    chatHistory: ChatMessage[];
    chatRunning: boolean;
    scrollEl?: HTMLDivElement | null;
    onApplyEvidence?: (suggestion: PlotSuggestion) => void | Promise<void>;
    onApplyNote?: (suggestion: PlotSuggestion) => void | Promise<void>;
  }

  let {
    chatHistory,
    chatRunning,
    scrollEl = $bindable(null),
    onApplyEvidence,
    onApplyNote,
  }: Props = $props();

  let copiedKey = $state("");
  let applyingKey = $state("");
  let appliedKey = $state("");
  let applyErrorKey = $state("");
  let copyResetTimer: ReturnType<typeof setTimeout> | null = null;
  let applyResetTimer: ReturnType<typeof setTimeout> | null = null;

  onDestroy(() => {
    if (copyResetTimer) clearTimeout(copyResetTimer);
    if (applyResetTimer) clearTimeout(applyResetTimer);
  });

  function suggestionKey(
    suggestion: PlotSuggestion,
    messageIndex: number,
    index: number,
    action: "proposed_change" | "evidence_to_add" | "apply_evidence" | "apply_note",
  ): string {
    return `${messageIndex}-${suggestion.kind}-${suggestion.target_card_id}-${suggestion.target_claim_id}-${index}-${action}`;
  }

  async function copySuggestion(
    suggestion: PlotSuggestion,
    key: string,
    field: "proposed_change" | "evidence_to_add",
  ): Promise<void> {
    const text = plotSuggestionClipboardText(suggestion, field);
    if (!text.trim()) return;
    try {
      await navigator.clipboard.writeText(text);
      copiedKey = key;
      if (copyResetTimer) clearTimeout(copyResetTimer);
      copyResetTimer = setTimeout(() => {
        copiedKey = "";
        copyResetTimer = null;
      }, 1600);
    } catch {
      copiedKey = "";
    }
  }

  async function applyEvidenceSuggestion(suggestion: PlotSuggestion, key: string): Promise<void> {
    if (!onApplyEvidence || !suggestion.target_claim_id || !suggestion.evidence_to_add.trim()) return;
    await applySuggestion(suggestion, key, onApplyEvidence);
  }

  async function applyNoteSuggestion(suggestion: PlotSuggestion, key: string): Promise<void> {
    if (!onApplyNote || !suggestion.target_claim_id || !suggestion.proposed_change.trim()) return;
    await applySuggestion(suggestion, key, onApplyNote);
  }

  async function applySuggestion(
    suggestion: PlotSuggestion,
    key: string,
    handler: (suggestion: PlotSuggestion) => void | Promise<void>,
  ): Promise<void> {
    applyingKey = key;
    applyErrorKey = "";
    try {
      await handler(suggestion);
      appliedKey = key;
      if (applyResetTimer) clearTimeout(applyResetTimer);
      applyResetTimer = setTimeout(() => {
        appliedKey = "";
        applyResetTimer = null;
      }, 1800);
    } catch {
      applyErrorKey = key;
    } finally {
      applyingKey = "";
    }
  }
</script>

<div class="cbv-messages" bind:this={scrollEl} aria-label="Chat history">
  {#if chatHistory.length === 0}
    <p class="cbv-empty">No messages yet. Ctrl/⌘+Enter to send.</p>
  {/if}
  {#each chatHistory as message, i (i)}
    <div class="cbv-message cbv-message-{message.role}">
      <header class="cbv-message-role">
        {#if message.role === "assistant"}Claude<span class="cbv-role-dot" aria-hidden="true"></span>{:else}You{/if}
      </header>
      {#if message.thinking}
        <details class="cbv-thinking" open={chatRunning && i === chatHistory.length - 1 && !message.content}>
          <summary>Thinking</summary>
          <div class="cbv-message-rendered">{@html renderChatContent(message.thinking)}</div>
        </details>
      {/if}
      {#if chatRunning && i === chatHistory.length - 1 && message.role === "assistant" && !message.content && !message.thinking}
        <div class="cbv-message-content cbv-typing">…thinking</div>
      {:else if message.content}
        {#if message.role === "assistant"}
          {@const suggestions = parsePlotSuggestions(message.content)}
          {@const renderedContent = stripPlotSuggestions(message.content)}
          {#if renderedContent}
            <div class="cbv-message-content cbv-message-rendered">{@html renderChatContent(renderedContent)}</div>
          {/if}
          {#if suggestions.length > 0}
            <div class="cbv-plot-suggestions" aria-label="Plot suggestions">
              <header>Plot suggestions</header>
              {#each suggestions as suggestion, j (`${suggestion.kind}-${suggestion.target_card_id}-${suggestion.target_claim_id}-${j}`)}
                <article class="cbv-plot-suggestion">
                  <div class="cbv-plot-suggestion-head">
                    <strong>{suggestion.title || "Untitled suggestion"}</strong>
                    <span>{suggestion.kind.replace(/_/g, " ")}</span>
                  </div>
                  {#if suggestion.proposed_change}
                    <p>{suggestion.proposed_change}</p>
                  {/if}
                  {#if suggestion.reason}
                    <small>Reason: {suggestion.reason}</small>
                  {/if}
                  {#if suggestion.evidence_to_add}
                    <small>Evidence to add: {suggestion.evidence_to_add}</small>
                  {/if}
                  <div class="cbv-plot-suggestion-targets">
                    {#if suggestion.target_card_id}<code>{suggestion.target_card_id}</code>{/if}
                    {#if suggestion.target_claim_id}<code>{suggestion.target_claim_id}</code>{/if}
                    {#if suggestion.template_instance_id}<code>{suggestion.template_instance_id}</code>{/if}
                    {#if suggestion.plot_point_id}<code>{suggestion.plot_point_id}</code>{/if}
                  </div>
                  <div class="cbv-plot-suggestion-actions">
                    {#if suggestion.proposed_change}
                      {@const changeKey = suggestionKey(suggestion, i, j, "proposed_change")}
                      <button
                        type="button"
                        title="Copy proposed change"
                        onclick={() => void copySuggestion(suggestion, changeKey, "proposed_change")}
                      >
                        <i class="ti ti-copy" aria-hidden="true"></i>
                        {copiedKey === changeKey ? "Copied" : "Copy change"}
                      </button>
                    {/if}
                    {#if suggestion.proposed_change && suggestion.target_claim_id && onApplyNote}
                      {@const applyNoteKey = suggestionKey(suggestion, i, j, "apply_note")}
                      <button
                        type="button"
                        title="Append this proposed change to the target claim's AI notes"
                        disabled={Boolean(applyingKey)}
                        onclick={() => void applyNoteSuggestion(suggestion, applyNoteKey)}
                      >
                        <i class="ti ti-check" aria-hidden="true"></i>
                        {applyingKey === applyNoteKey ? "Applying" : appliedKey === applyNoteKey ? "Applied" : "Apply note"}
                      </button>
                      {#if applyErrorKey === applyNoteKey}
                        <small class="cbv-plot-suggestion-action-error">Could not apply note.</small>
                      {/if}
                    {/if}
                    {#if suggestion.evidence_to_add}
                      {@const evidenceKey = suggestionKey(suggestion, i, j, "evidence_to_add")}
                      <button
                        type="button"
                        title="Copy evidence to add"
                        onclick={() => void copySuggestion(suggestion, evidenceKey, "evidence_to_add")}
                      >
                        <i class="ti ti-copy" aria-hidden="true"></i>
                        {copiedKey === evidenceKey ? "Copied" : "Copy evidence"}
                      </button>
                    {/if}
                    {#if suggestion.evidence_to_add && suggestion.target_claim_id && onApplyEvidence}
                      {@const applyKey = suggestionKey(suggestion, i, j, "apply_evidence")}
                      <button
                        type="button"
                        title="Append this evidence to the target claim"
                        disabled={Boolean(applyingKey)}
                        onclick={() => void applyEvidenceSuggestion(suggestion, applyKey)}
                      >
                        <i class="ti ti-check" aria-hidden="true"></i>
                        {applyingKey === applyKey ? "Applying" : appliedKey === applyKey ? "Applied" : "Apply evidence"}
                      </button>
                      {#if applyErrorKey === applyKey}
                        <small class="cbv-plot-suggestion-action-error">Could not apply evidence.</small>
                      {/if}
                    {/if}
                  </div>
                </article>
              {/each}
            </div>
          {/if}
        {:else}
          <div class="cbv-message-content">{message.content}</div>
        {/if}
      {/if}
      {#if message.truncated}
        <div class="cbv-truncated">Response cut off — hit max tokens.</div>
      {/if}
      {#if message.journal_added && message.journal_added.length > 0}
        <div class="cbv-journal-added" title="Lore auto-detected from this turn.">
          <span class="cbv-journal-label">Auto-added context:</span>
          {#each message.journal_added as entry (entry.entry_id)}
            <span class="cbv-journal-chip">{entry.title || entry.entry_id}</span>
          {/each}
        </div>
      {/if}
      {#if message.role === "assistant" && message.usage}
        {@const totalIn = message.usage.input_tokens + message.usage.cached_input_tokens + message.usage.cache_write_tokens}
        {@const cachePct = totalIn > 0 ? Math.round((message.usage.cached_input_tokens / totalIn) * 100) : 0}
        <div class="cbv-turn-meta">
          {totalIn} → {message.usage.output_tokens} tok
          {#if cachePct > 0}<span> · {cachePct}% cached</span>{/if}
          {#if message.cost_usd != null}<span> · {formatCostEur(message.cost_usd)}</span>{/if}
        </div>
      {/if}
    </div>
  {/each}
</div>

<style>
  .cbv-empty {
    margin: 0;
    font-size: var(--fs-md);
    color: var(--text-3);
  }

  /* ---- 4 · messages ---- */
  .cbv-messages {
    flex: 1 1 0; min-height: 96px; overflow-y: auto;
    display: flex; flex-direction: column; gap: 16px; padding: 16px 14px;
  }
  .cbv-message { display: flex; flex-direction: column; gap: 6px; max-width: 100%; }
  .cbv-message-user { align-items: flex-end; }
  .cbv-message-assistant { align-items: flex-start; }
  .cbv-message-role {
    display: flex; align-items: center; gap: 6px; font-size: var(--fs-xs); font-weight: 800;
    letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-3); padding: 0 2px;
  }
  .cbv-role-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--k-graphite); }
  .cbv-message-content {
    font-size: var(--fs-md); line-height: 1.6; white-space: pre-wrap; padding: 10px 13px;
  }
  .cbv-message-user .cbv-message-content {
    max-width: 78%; border-radius: 13px 13px 4px 13px;
    background: var(--accent-soft); border: 1px solid var(--accent-soft2); color: var(--text);
  }
  .cbv-message-assistant .cbv-message-content {
    max-width: 82%; border-radius: 13px 13px 13px 4px; white-space: normal;
    background: var(--surface); border: 1px solid var(--border); box-shadow: 0 1px 3px var(--shadow); color: var(--text);
    padding: 11px 14px;
  }
  .cbv-typing { font-style: italic; color: var(--text-3); }
  :global(.cbv-message-rendered) { font-size: var(--fs-md); line-height: 1.6; }
  :global(.cbv-message-rendered p) { margin: 0 0 0.6em; }
  :global(.cbv-message-rendered p:last-child) { margin-bottom: 0; }
  :global(.cbv-message-rendered pre) {
    margin: 0.4em 0; padding: 8px 10px; background: var(--inset); border-radius: 8px; overflow-x: auto;
  }
  :global(.cbv-message-rendered code) { font-family: var(--mono); font-size: var(--fs-sm); }

  /* 4a · thinking accordion. */
  .cbv-thinking {
    max-width: 82%; font-size: var(--fs-sm); color: var(--text-3);
    border: 1px solid var(--divider); border-radius: 9px; background: var(--inset); padding: 5px 11px;
  }
  .cbv-thinking summary { cursor: pointer; list-style: none; }
  .cbv-thinking summary::-webkit-details-marker { display: none; }
  .cbv-thinking summary::before { content: "▸  "; color: var(--text-3); }
  .cbv-thinking[open] summary::before { content: "▾  "; }

  /* 4d · truncation banner. */
  .cbv-truncated {
    display: inline-flex; align-items: center; gap: 7px; padding: 7px 12px;
    border: 1px solid var(--star-border); border-radius: 9px; background: var(--star-soft);
    font-size: var(--fs-sm); color: var(--star);
  }
  .cbv-truncated::before { content: "⚠"; }

  /* 4b · journal-added chip. */
  .cbv-journal-added {
    display: inline-flex; flex-wrap: wrap; gap: 5px 6px; align-items: center; font-size: var(--fs-xs);
  }
  .cbv-journal-label {
    font-size: var(--fs-xs); font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-3);
  }
  .cbv-journal-chip {
    display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border-radius: 999px;
    background: var(--accent-soft); border: 1px solid var(--accent-soft2);
    color: var(--accent-emphasis); font-weight: 600;
  }
  .cbv-journal-chip::before { content: "✚"; font-size: var(--fs-xs); }

  /* 4c · per-turn usage meta. */
  .cbv-turn-meta {
    display: flex; align-items: center; gap: 12px; padding: 0 2px;
    font-family: var(--mono); font-size: var(--fs-xs); color: var(--text-3);
  }

  .cbv-plot-suggestions {
    max-width: 82%;
    display: grid;
    gap: 8px;
    color: var(--text);
  }
  .cbv-plot-suggestions > header {
    font-size: var(--fs-xs);
    font-weight: 800;
    letter-spacing: 0;
    text-transform: uppercase;
    color: var(--accent-emphasis);
  }
  .cbv-plot-suggestion {
    display: grid;
    gap: 5px;
    padding: 9px 10px;
    border: 1px solid var(--accent-soft2);
    border-radius: 8px;
    background: var(--accent-soft);
  }
  .cbv-plot-suggestion-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
  }
  .cbv-plot-suggestion-head strong {
    font-size: var(--fs-sm);
    font-weight: 700;
  }
  .cbv-plot-suggestion-head span,
  .cbv-plot-suggestion small {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .cbv-plot-suggestion p {
    margin: 0;
    font-size: var(--fs-sm);
    line-height: 1.45;
  }
  .cbv-plot-suggestion-targets {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
  }
  .cbv-plot-suggestion-targets code {
    padding: 2px 6px;
    border-radius: 5px;
    background: var(--inset);
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--text-2);
  }
  .cbv-plot-suggestion-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding-top: 2px;
  }
  .cbv-plot-suggestion-actions button {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 8px;
    border-radius: 6px;
    border: 1px solid var(--accent-soft2);
    background: var(--surface);
    color: var(--text-2);
    font: inherit;
    font-size: var(--fs-xs);
    cursor: pointer;
  }
  .cbv-plot-suggestion-actions button:hover {
    background: var(--inset);
  }
  .cbv-plot-suggestion-actions button:disabled {
    cursor: wait;
    opacity: 0.65;
  }
  .cbv-plot-suggestion-action-error {
    align-self: center;
    color: var(--danger);
  }
</style>
