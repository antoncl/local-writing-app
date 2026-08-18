<script lang="ts">
  import type { AssistantEntrySummary, ChatSessionSummary, PromptEntrySummary, ViewSpec } from "@/lib/types";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import { defaultView } from "@/lib/views/evaluateView";
  import { chatSummariesToEvalNodes, type ChatEvalNode } from "@/lib/views/chatNodes";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { formatCostEur } from "@/lib/utils/money";

  let {
    sessions,
    // The view to render through, resolved by App from the pane's selected view
    // (paneViews.specFor("chat", …)); the standalone default is the kind's honest
    // default view — the whole roster in the backend's pinned-first / last-active
    // order (ADR-0037 §7). A chat is now a real node (ADR-0051 S1/S6), so the pane
    // stops being a `nodeSet()` bypass and becomes designable like Lore/Assistants.
    viewSpec = defaultView("chat"),
    activeChatId = null,
    // Passed so the per-session preset line resolves prompt/assistant names
    // reactively (App owns both lists); resolving via props rather than a
    // callback keeps the lookups tracking their inputs. `promptEntries` also
    // resolves each chat's seeding-prompt output kind for the "Openable" view.
    promptEntries,
    assistantEntries,
    // App owns the editor pane set + error wrapper, so open/delete are callbacks.
    onOpenChat,
    onDeleteChat,
  }: {
    sessions: ChatSessionSummary[];
    viewSpec?: ViewSpec;
    activeChatId?: string | null;
    promptEntries: PromptEntrySummary[];
    assistantEntries: AssistantEntrySummary[];
    onOpenChat: (chatId: string) => void;
    onDeleteChat: (chatId: string) => void;
  } = $props();

  const schema = $derived($metadataSchemaStore);
  // Lift each roster summary to an EvalNode: `subject` and the seeding prompt's
  // derived `seed_disposition` go in metadata (ADR-0029 §D), so a designed or
  // built-in view can group/filter by subject and hide the brainstorm ("Revise
  // entities") chats. The lift is shared with the view-designer preview.
  const chatNodes = $derived(chatSummariesToEvalNodes(sessions, promptEntries, schema));
  const view = $derived({ spec: viewSpec, universe: chatNodes, schema, referenceIndex: $referenceIndexStore });

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
  {view}
  active={(node) => activeChatId === node.id}
  onClick={(node) => onOpenChat(node.id)}
  row={chatRow}
>
  {#snippet whenEmpty()}
    {#if sessions.length === 0}
      <p class="muted">No chats yet. Click + to start one.</p>
    {:else}
      <p class="muted">No chats match this view.</p>
    {/if}
  {/snippet}
</ViewNodeList>

{#snippet chatRow(session: ChatEvalNode, ctx: RowCtx<ChatEvalNode>)}
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
      <button class="row-action-delete" type="button" title="Delete chat" onclick={(event) => { event.stopPropagation(); onDeleteChat(session.id); }}>×</button>
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
