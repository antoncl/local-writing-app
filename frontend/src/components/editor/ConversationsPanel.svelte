<script lang="ts">
  // The Conversations surface on a node (ADR-0051 S3). Replaces the header-verb
  // brainstorm launcher (EntryBrainstormBar), whose one affordance always minted
  // a *new* chat — the duplicate-spawn bug this slice removes. The surface lists
  // the chats already about this node **resume-first** so the writer reuses the
  // thread (context intact) instead of spawning a twin, with an explicit **＋New**
  // menu as the only spawn path (anti-goal: no auto-create on click).
  //
  // Not a bespoke chat widget (the smell the ADR names): membership is the same
  // reverse-reference lookup the Backlinks panel runs (`conversationsFor` over the
  // in-memory reverse index), and rows render through NodeRow / ViewNodeList like
  // every other node list. The ＋New menu offers the entry_patch (brainstorm)
  // prompts applicable here — the same set EntryBrainstormBar computed, now shown
  // as a menu so every applicable prompt is reachable, not just the first.

  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import Popover from "@/components/chrome/Popover.svelte";
  import { nodeSet } from "@/lib/views/viewResult";
  import { chatSessions } from "@/lib/stores/chatSessions.svelte";
  import { chatSessionsStore } from "@/lib/stores/chats";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { hiddenLibraryStore } from "@/lib/stores/hiddenLibrary";
  import { conversationsFor } from "@/lib/views/conversations";
  import {
    promptEntriesForSurface,
    type PromptResolutionContext,
  } from "@/lib/editor-core/promptResolution";
  import type { ChatSessionSummary, MetadataSchema, PromptEntrySummary } from "@/lib/types";

  let {
    subjectId,
    subjectTitle = "",
    promptEntries,
    metadataSchema,
    hostPaneId = null,
  }: {
    subjectId: string;
    // The subject's display title — names a launched chat "<subject> — <prompt>"
    // (ADR-0051 S2), so two brainstorms of the same entry don't collide.
    subjectTitle?: string;
    promptEntries: PromptEntrySummary[];
    metadataSchema: MetadataSchema | null;
    // The editor pane hosting this panel; a launched chat registers as its
    // subordinate so it auto-closes when this node's pane closes.
    hostPaneId?: string | null;
  } = $props();

  // The chats about this node, resume-first (roster order = pinned, then most
  // recently updated). ViewNodeList wants an `entry_type`; a ChatSessionSummary
  // has none, so stamp the constant (as the Chats pane does) — it is never
  // grouped on (nodeSet ⇒ flat).
  type ConversationNode = ChatSessionSummary & { entry_type: string };
  let conversations = $derived(
    conversationsFor(subjectId, $referenceIndexStore, $chatSessionsStore),
  );
  let conversationNodes = $derived(
    conversations.map((session): ConversationNode => ({ ...session, entry_type: "chat" })),
  );

  let ctx = $derived<PromptResolutionContext>({
    metadataSchema,
    promptEntries,
    loreEntries: [],
    availableScenes: [],
    hiddenPromptIds: $hiddenLibraryStore,
  });
  // The brainstorm prompts applicable to this node — the ＋New menu. (Broader
  // conversation kinds join when `subject` generalizes `target_scene_id`, S5.)
  let newPrompts = $derived(promptEntriesForSurface(ctx, "entry_patch"));

  // Expanded by default: the point of the surface is that the writer sees an
  // existing thread to resume before reaching for ＋New.
  let expanded = $state(true);
  let menuOpen = $state(false);
  let newButton: HTMLButtonElement | null = $state(null);

  async function startNew(prompt: PromptEntrySummary): Promise<void> {
    menuOpen = false;
    if (!prompt || !subjectId) return;
    // This node IS the subject (ADR-0051 S2): stamp it so the new chat surfaces
    // here and is named after this node.
    await chatSessions.openChatFromPromptEntry(prompt, { entry: subjectId }, null, {
      parentPaneId: hostPaneId,
      subject: subjectId,
      subjectTitle,
    });
  }
</script>

{#if conversations.length > 0 || newPrompts.length > 0}
  <section class="entry-conversations" aria-label="Conversations">
    <NodeRow
      title="Conversations"
      groupHeader
      collapsed={!expanded}
      onClick={() => (expanded = !expanded)}
    >
      {#snippet leading()}
        <GroupCaret collapsed={!expanded} />
      {/snippet}
      {#snippet trailing()}
        <span class="conv-header-trailing">
          <CountPill count={conversations.length} />
          {#if newPrompts.length > 0}
            <span class="conv-new-wrap">
              <button
                bind:this={newButton}
                type="button"
                class="conv-new"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                aria-controls="conversations-new-menu"
                title="Start a new conversation about this entry"
                onclick={(event) => {
                  event.stopPropagation();
                  menuOpen = !menuOpen;
                }}
              >＋ New</button>
              <Popover
                bind:open={menuOpen}
                triggerEl={newButton}
                role="menu"
                id="conversations-new-menu"
                label="Start a new conversation"
                offset={6}
                anchor="right"
                minWidth="200px"
                maxWidth="320px"
              >
                {#each newPrompts as prompt (prompt.id)}
                  <button
                    type="button"
                    class="conv-new-item"
                    role="menuitem"
                    onclick={() => void startNew(prompt)}
                  >{prompt.title}</button>
                {/each}
              </Popover>
            </span>
          {/if}
        </span>
      {/snippet}
      {#snippet nested()}
        <ViewNodeList
          result={nodeSet(conversationNodes)}
          mode="tree"
          onClick={(node) => void editorPanes.openChat(node.id)}
          row={conversationRow}
        >
          {#snippet whenEmpty()}
            <p class="muted">No conversations yet — start one with ＋New.</p>
          {/snippet}
        </ViewNodeList>
      {/snippet}
    </NodeRow>
  </section>
{/if}

{#snippet conversationRow(session: ConversationNode, ctx: RowCtx<ConversationNode>)}
  <NodeRow title={session.title || "Untitled chat"} depth={ctx.depth} onClick={ctx.onClick}>
    {#snippet detailSlot()}
      <small>
        {session.message_count} message{session.message_count === 1 ? "" : "s"} · {session.updated_at.slice(0, 16).replace("T", " ")}
      </small>
    {/snippet}
  </NodeRow>
{/snippet}

<style>
  .entry-conversations {
    padding-top: 8px;
  }

  .conv-header-trailing {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }

  /* The ＋New menu anchors against this relative wrapper (Popover positions in
     flow, not portalled). */
  .conv-new-wrap {
    position: relative;
    display: inline-flex;
  }

  /* A quiet text button (design language — no glyph beyond the ＋). */
  .conv-new {
    font: inherit;
    font-size: var(--fs-xs);
    padding: 2px 8px;
    border-radius: var(--r-sm);
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-2);
    cursor: pointer;
    white-space: nowrap;
  }
  .conv-new:hover {
    color: var(--text);
    border-color: var(--accent);
  }

  .conv-new-item {
    display: block;
    width: 100%;
    padding: 8px 10px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    text-align: left;
    font-size: var(--fs-md);
    color: var(--text);
    cursor: pointer;
    white-space: nowrap;
  }
  .conv-new-item:hover {
    background: var(--panel);
  }
</style>
