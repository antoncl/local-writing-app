<script lang="ts">
  import type { AssistantEntrySummary, ChatSessionSummary, PromptEntrySummary } from "@/lib/types";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { nodeSet } from "@/lib/views/viewResult";
  import { formatCostEur } from "@/lib/utils/money";

  export let sessions: ChatSessionSummary[];

  // A non-view pane (ADR-0035 §3, #253): a pre-computed roster with no view to
  // evaluate. It lifts its array to the degenerate ViewResult via `nodeSet()` and
  // renders through the same ViewNodeList wrapper as the view panes — one render
  // path, no bespoke NodeList. A ChatSessionSummary has no `entry_type`, so we
  // stamp a constant to satisfy EvalNode; it is never grouped on (nodeSet ⇒ flat).
  type ChatNode = ChatSessionSummary & { entry_type: string };
  $: chatNodes = sessions.map((session): ChatNode => ({ ...session, entry_type: "chat" }));
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

<ViewNodeList
  result={nodeSet(chatNodes)}
  active={(node) => activeChatId === node.id}
  onClick={(node) => onOpenChat(node.id)}
  row={chatRow}
>
  {#snippet whenEmpty()}
    <p class="muted">No chats yet. Click + to start one.</p>
  {/snippet}
</ViewNodeList>

{#snippet chatRow(session: ChatNode, ctx: RowCtx<ChatNode>)}
  <NodeRow
    title={session.title || "Untitled chat"}
    depth={ctx.depth}
    active={ctx.active}
    onClick={ctx.onClick}
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
{/snippet}

<style>
  /* Rendered inside NodeRow's detailSlot snippet, so these carry Chats'
     scope hash — the old `.chats-pane` ancestor anchor (App's pane wrapper)
     is no longer needed; scoping limits them to this component. */
  .chat-prompt-glyph {
    font-size: var(--fs-md);
  }

  .chat-session-preset {
    color: var(--accent);
    font-size: var(--fs-xs);
  }

  .chat-session-cost {
    color: var(--text-2);
    font-variant-numeric: tabular-nums;
  }
</style>
