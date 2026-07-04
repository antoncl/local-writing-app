<!--
  ChatTranscript — presentational message list for ChatBodyView (#99).
  Pure render of chatHistory; owns no state. The scroll element is bound
  back to the parent via `bind:scrollEl` so ChatBodyView keeps driving
  scroll-to-bottom during streaming exactly as before.
-->
<script lang="ts">
  import { renderChatContent } from "@/lib/utils/chatMessageRender";
  import { formatCostEur } from "@/lib/utils/money";
  import type { ChatMessage } from "@/lib/types";

  interface Props {
    chatHistory: ChatMessage[];
    chatRunning: boolean;
    scrollEl?: HTMLDivElement | null;
  }

  let { chatHistory, chatRunning, scrollEl = $bindable(null) }: Props = $props();
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
          <div class="cbv-message-content cbv-message-rendered">{@html renderChatContent(message.content)}</div>
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
    font-size: 13px;
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
    display: flex; align-items: center; gap: 6px; font-size: 10px; font-weight: 800;
    letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-3); padding: 0 2px;
  }
  .cbv-role-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--k-graphite); }
  .cbv-message-content {
    font-size: 13.5px; line-height: 1.6; white-space: pre-wrap; padding: 10px 13px;
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
  :global(.cbv-message-rendered) { font-size: 13.5px; line-height: 1.6; }
  :global(.cbv-message-rendered p) { margin: 0 0 0.6em; }
  :global(.cbv-message-rendered p:last-child) { margin-bottom: 0; }
  :global(.cbv-message-rendered pre) {
    margin: 0.4em 0; padding: 8px 10px; background: var(--inset); border-radius: 8px; overflow-x: auto;
  }
  :global(.cbv-message-rendered code) { font-family: ui-monospace, "JetBrains Mono", monospace; font-size: 12.5px; }

  /* 4a · thinking accordion. */
  .cbv-thinking {
    max-width: 82%; font-size: 11.5px; color: var(--text-3);
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
    font-size: 11.5px; color: var(--star);
  }
  .cbv-truncated::before { content: "⚠"; }

  /* 4b · journal-added chip. */
  .cbv-journal-added {
    display: inline-flex; flex-wrap: wrap; gap: 5px 6px; align-items: center; font-size: 11px;
  }
  .cbv-journal-label {
    font-size: 9.5px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-3);
  }
  .cbv-journal-chip {
    display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border-radius: 999px;
    background: var(--accent-soft); border: 1px solid var(--accent-soft2);
    color: var(--accent-strong); font-weight: 600;
  }
  .cbv-journal-chip::before { content: "✚"; font-size: 9px; }

  /* 4c · per-turn usage meta. */
  .cbv-turn-meta {
    display: flex; align-items: center; gap: 12px; padding: 0 2px;
    font-family: ui-monospace, "JetBrains Mono", monospace; font-size: 10.5px; color: var(--text-3);
  }
</style>
