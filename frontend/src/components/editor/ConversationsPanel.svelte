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
  // in-memory reverse index), and the rows render through NodeRow / ViewNodeList
  // like every other node list. The ＋New menu offers the brainstorm (commit-
  // carrying, ADR-0054 §2) prompts applicable here — the same set EntryBrainstormBar
  // computed, now shown as a menu so every applicable prompt is reachable, not just
  // the first.
  //
  // The header is a purpose-built disclosure row, NOT a NodeRow group header: the
  // ＋New menu is an interactive Popover, and NodeRow styles every <button> in its
  // trailing slot as a fixed-size icon tile (`.node-row-trailing :global(button)`)
  // — which would flatten the menu items. Only the LIST reuses NodeRow/ViewNodeList
  // (the reuse the ADR actually asks for); the header is minor chrome.

  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import Popover from "@/components/chrome/Popover.svelte";
  import PromptMenu from "@/components/editor/PromptMenu.svelte";
  import { buildPromptMenuTree } from "@/lib/editor-core/promptMenuTree";
  import { nodeSet } from "@/lib/views/viewResult";
  import { resolveColor } from "@/lib/utils/colors";
  import { chatSessions } from "@/lib/stores/chatSessions.svelte";
  import { chatSessionsStore } from "@/lib/stores/chats";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { referenceIndexStore } from "@/lib/stores/references";
  import { hiddenLibraryStore } from "@/lib/stores/hiddenLibrary";
  import { conversationsFor } from "@/lib/views/conversations";
  import {
    promptEntriesOfferedOn,
    type PromptResolutionContext,
  } from "@/lib/editor-core/promptResolution";
  import { seedSubjectEntryInput } from "@/components/editor/body/chat/chatInputs";
  import type {
    ChatSessionSummary,
    MetadataSchema,
    NodePickerRef,
    PromptEntrySummary,
  } from "@/lib/types";

  let {
    subjectId,
    subjectTitle = "",
    subjectEntryType = "",
    asOfScene = "",
    promptEntries,
    metadataSchema,
    hostPaneId = null,
  }: {
    subjectId: string;
    // The subject's display title — names a launched chat "<subject> — <prompt>"
    // (ADR-0051 S2), so two brainstorms of the same entry don't collide.
    subjectTitle?: string;
    // The subject node's schema entry_type (e.g. lore:character, plot:card). It
    // scopes the ＋New menu to the brainstorm prompts THIS node can be the subject
    // of (ADR-0048 S8b) — a lore entry offers the lore revise prompt, a plot card
    // the plot-card one, a scene the scene-summary one, not cross. Empty until
    // resolved ⇒ no brainstorm prompts shown.
    subjectEntryType?: string;
    // The scene the subject's time-travel slider is currently at (ADR-0055 §1).
    // Launch seeds it onto the prompt's `as_of` scene input so a subject-anchored
    // conversation (impersonate) reads its subject as-of here. "" = book-start.
    asOfScene?: string;
    promptEntries: PromptEntrySummary[];
    metadataSchema: MetadataSchema | null;
    // The editor pane hosting this panel; a launched chat registers as its
    // subordinate so it auto-closes when this node's pane closes.
    hostPaneId?: string | null;
  } = $props();

  // The chats about this node, resume-first (roster order = pinned, then most
  // recently updated). A ChatSessionSummary now carries its `entry_type`
  // (ADR-0051 S6), so it already satisfies EvalNode — no stamp. This surface
  // stays a plain resume-first list (nodeSet ⇒ flat, ungrouped); the designable
  // view is the global Chats pane's, not this per-entry one.
  let conversations = $derived(
    conversationsFor(subjectId, $referenceIndexStore, $chatSessionsStore),
  );

  let ctx = $derived<PromptResolutionContext>({
    metadataSchema,
    promptEntries,
    loreEntries: [],
    availableScenes: [],
    hiddenPromptIds: $hiddenLibraryStore,
  });
  // The prompts applicable to this node — the ＋New menu. The conversation
  // prompts whose `offer_on` allow-list admits THIS node's type
  // (ADR-0054 §4/S4) — a lore entry offers the lore revise prompt, a plot card
  // the plot-card one, a scene the scene-summary one, a character both the revise
  // prompt and impersonate, never cross. Both committing brainstorms and plain
  // conversations qualify. The menu hides itself when none resolves.
  let newPrompts = $derived(promptEntriesOfferedOn(ctx, subjectEntryType));
  // Prompt titles with "/" fold into a navigable submenu (#832); a flat list of
  // slashless titles yields a flat menu, unchanged.
  let newMenu = $derived(buildPromptMenuTree(newPrompts));

  // Per-instance so two lore entries open in separate panes don't collide on a
  // shared DOM id (aria-controls / the Popover panel id).
  let menuId = $derived(`conversations-new-menu-${subjectId}`);

  // Expanded by default: the point of the surface is that the writer sees an
  // existing thread to resume before reaching for ＋New.
  let expanded = $state(true);
  let menuOpen = $state(false);
  let newButton: HTMLButtonElement | null = $state(null);

  async function startNew(prompt: PromptEntrySummary): Promise<void> {
    menuOpen = false;
    if (!prompt || !subjectId) return;
    // This node IS the subject (ADR-0051 S2): stamp it so the new chat surfaces
    // here and is named after this node, and seed it into the prompt's `entry`
    // target in that input's own shape (#1094) — a `context_pick` (the revise
    // prompts' target) needs an array-shaped ref, not the bare id that made a
    // required plotline/plot-card target fail "Missing required" on send. The
    // subject's kind is the FQN prefix of its entry_type (kind:key).
    const subjectKind = (subjectEntryType.split(":")[0] || "lore") as NodePickerRef["kind"];
    const seededInputs: Record<string, unknown> = {
      entry: seedSubjectEntryInput(prompt, {
        id: subjectId,
        kind: subjectKind,
        title: subjectTitle,
        entryType: subjectEntryType || undefined,
      }),
    };
    // Seed the read anchor onto the prompt's `as_of` scene input (ADR-0055 §1) —
    // hidden from the chat strip but persisted, so impersonate reads the subject
    // as-of the slider's scene; omitted at book-start (a prompt without an
    // `as_of` input ignores the seed).
    if (asOfScene) seededInputs.as_of = asOfScene;
    await chatSessions.openChatFromPromptEntry(prompt, seededInputs, null, {
      parentPaneId: hostPaneId,
      subject: subjectId,
      subjectTitle,
    });
  }
</script>

{#if conversations.length > 0 || newPrompts.length > 0}
  <section class="entry-conversations" aria-label="Conversations">
    <div class="conv-header">
      <button
        type="button"
        class="conv-toggle"
        aria-expanded={expanded}
        onclick={() => (expanded = !expanded)}
      >
        <GroupCaret collapsed={!expanded} />
        <span class="conv-title">Conversations</span>
        <CountPill count={conversations.length} />
      </button>
      {#if newPrompts.length > 0}
        <div class="conv-new-wrap">
          <button
            bind:this={newButton}
            type="button"
            class="conv-new"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            aria-controls={menuId}
            title="Start a new conversation about this entry"
            onclick={() => (menuOpen = !menuOpen)}
          >＋ New</button>
          <Popover
            bind:open={menuOpen}
            triggerEl={newButton}
            role="menu"
            id={menuId}
            label="Start a new conversation"
            offset={6}
            anchor="right"
            minWidth="200px"
            maxWidth="320px"
          >
            <PromptMenu nodes={newMenu} onSelect={(prompt) => void startNew(prompt)} />
          </Popover>
        </div>
      {/if}
    </div>
    {#if expanded}
      <div class="conv-list">
        <ViewNodeList
          result={nodeSet(conversations)}
          mode="tree"
          onClick={(node) => void editorPanes.openChat(node.id)}
          row={conversationRow}
        >
          {#snippet whenEmpty()}
            <p class="muted">No conversations yet — start one with ＋New.</p>
          {/snippet}
        </ViewNodeList>
      </div>
    {/if}
  </section>
{/if}

{#snippet conversationRow(session: ChatSessionSummary, rowCtx: RowCtx<ChatSessionSummary>)}
  <NodeRow
    title={session.title || "Untitled chat"}
    depth={rowCtx.depth}
    stripeColor={resolveColor(null, session.entry_type, "chat", metadataSchema)?.hex ?? null}
    onClick={rowCtx.onClick}
  >
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

  /* Disclosure header — mirrors the group-header treatment (serif title +
     hairline rule) without borrowing NodeRow, whose trailing slot flattens
     interactive buttons into icon tiles. */
  .conv-header {
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 1px solid var(--divider);
    padding-bottom: 4px;
    margin-bottom: 6px;
  }

  .conv-toggle {
    flex: 1 1 auto;
    min-width: 0;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 4px 6px;
    border: none;
    border-radius: 4px;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .conv-toggle:hover {
    background: var(--accent-soft);
  }

  .conv-title {
    font-family: var(--serif);
    font-size: var(--fs-md);
    font-weight: 700;
    color: var(--text);
  }

  /* The ＋New menu anchors against this relative wrapper (Popover positions in
     flow, not portalled). */
  .conv-new-wrap {
    position: relative;
    display: inline-flex;
    flex: none;
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

  /* Tier panel behind the rows — matches NodeRow's grouped-children tint so the
     list reads as one grouped surface, the same as the Backlinks panel. */
  .conv-list {
    padding: 8px;
    background: var(--tier1);
    border-radius: 10px;
  }

  .muted {
    margin: 0;
    padding: 2px 4px;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
</style>
