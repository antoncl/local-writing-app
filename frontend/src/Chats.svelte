<script lang="ts">
  import type { AssistantEntrySummary, ChatSessionSummary, PromptEntrySummary } from "./types";
  import NodeRow from "./NodeRow.svelte";
  import NodeList from "./NodeList.svelte";
  import { formatCostEur } from "./money";

  export let sessions: ChatSessionSummary[];
  export let activeChatId: string | null = null;
  // Passed so the per-session preset line resolves prompt/assistant names
  // reactively (App owns both lists); resolving via props rather than a
  // callback keeps the lookups tracking their inputs.
  export let promptEntries: PromptEntrySummary[];
  export let assistantEntries: AssistantEntrySummary[];
  // App owns the editor pane set + error wrapper, so open/delete are callbacks.
  export let onOpenChat: (chatId: string) => void;
  export let onDeleteChat: (chatId: string) => void;

  function chatSessionPromptTitle(session: ChatSessionSummary): string {
    if (!session.prompt_entry_id) return "";
    const entry = promptEntries.find((p) => p.id === session.prompt_entry_id);
    return entry?.title || "Unknown prompt";
  }

  function assistantNameFor(assistantId: string): string {
    if (!assistantId) return "";
    return assistantEntries.find((a) => a.id === assistantId)?.title ?? "";
  }
</script>

<NodeList isEmpty={sessions.length === 0}>
  {#each sessions as session (session.id)}
    <NodeRow
      title={session.title || "Untitled chat"}
      active={activeChatId === session.id}
      onClick={() => onOpenChat(session.id)}
    >
      {#snippet detailSlot()}
        {#if session.prompt_entry_id || session.assistant_id}
          <small class="chat-session-preset">
            {#if session.prompt_entry_id}
              <span class="chat-prompt-glyph" aria-hidden="true">✨</span>
              {chatSessionPromptTitle(session)}
            {/if}
            {#if session.prompt_entry_id && session.assistant_id} · {/if}
            {#if session.assistant_id}
              {assistantNameFor(session.assistant_id) || "(unknown)"}
            {/if}
          </small>
        {/if}
        <small>
        {session.message_count} message{session.message_count === 1 ? "" : "s"} · {session.updated_at.slice(0, 16).replace("T", " ")}
        {#if (session.cost_usd_total ?? 0) > 0}
          · <span class="chat-session-cost">{formatCostEur(session.cost_usd_total ?? 0)}</span>
        {/if}
      </small>
      {/snippet}
      {#snippet trailing()}
        <button class="row-action-delete" type="button" title="Delete chat" on:click|stopPropagation={() => onDeleteChat(session.id)}>×</button>
      {/snippet}
    </NodeRow>
  {/each}
  {#snippet whenEmpty()}
    <p class="muted">No chats yet. Click + New Chat to start one.</p>
  {/snippet}
</NodeList>
