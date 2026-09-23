<script lang="ts">
  // The "Review items" computed collection field tab (ADR-0090 Amendment 2
  // §1) — the open review items whose dependent is THIS entry. Modelled on
  // ConversationsPanel.svelte: a RailSectionHeader (count + collapse key),
  // then a NodeList of NodeRows over the filtered todos — a review item is a
  // todo, not a kind, so this reduces to the existing widgets rather than
  // growing a bespoke list (CLAUDE.md's "app reduces to NodeRow/NodeEditor").
  //
  // Never writes anything itself: opening a row routes through the same
  // `todoActions.openFileTodo` the Todo pane uses (opens the source parked on
  // its baseline, then this dependent, per ADR-0090 §3/Amendment 2 §2). Each
  // row also gets a Propose tile (ADR-0090 §4) — the SAME ＋New prompt roster
  // ConversationsPanel offers on this entry's own type, since Propose opens a
  // conversation on this entry (the dependent), not on the row's source.
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import RailSectionHeader from "@/components/editor/RailSectionHeader.svelte";
  import Popover from "@/components/chrome/Popover.svelte";
  import PromptMenu from "@/components/editor/PromptMenu.svelte";
  import { buildPromptMenuTree } from "@/lib/editor-core/promptMenuTree";
  import {
    promptEntriesOfferedOn,
    proposeDefaultPrompt,
    type PromptResolutionContext,
  } from "@/lib/editor-core/promptResolution";
  import { seedConversationInputs } from "@/components/editor/body/chat/chatInputs";
  import { todosStore } from "@/lib/stores/todos";
  import { loreEntriesStore } from "@/lib/stores/lore";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { hiddenLibraryStore } from "@/lib/stores/hiddenLibrary";
  import { todoActions } from "@/lib/stores/todoActions.svelte";
  import { railSectionCollapse } from "@/lib/stores/railSectionCollapse.svelte";
  import { reviewItemSourceDetail } from "@/lib/utils/reviewItemDetail";
  import type { PromptEntrySummary, TodoItem } from "@/lib/types";

  let {
    nodeId,
    nodeTitle,
    subjectEntryType = "",
    promptEntries,
    asOfScene = "",
    asOfSceneTitle = "",
  }: {
    nodeId: string;
    nodeTitle: string;
    subjectEntryType?: string;
    promptEntries: PromptEntrySummary[];
    // The card's as-of scene (ADR-0055 §1) — Propose reads the dependent as
    // of the same scene the Conversations ＋New would, never book-start.
    asOfScene?: string;
    asOfSceneTitle?: string;
  } = $props();

  let items = $derived(
    $todosStore.filter((item) => item.scope === "node" && item.node_id === nodeId && item.status === "open"),
  );

  // The source's title, off the cheapest lookup already loaded (lore is the
  // only kind ADR-0090 sources from) — read through the store's own
  // subscription so a roster that loads after this panel mounts re-renders
  // the titles; falls back to the bare id when the source entry isn't in the
  // roster (deleted, or a project the roster hasn't loaded yet).
  let titleById = $derived(new Map($loreEntriesStore.map((entry) => [entry.id, entry.title] as const)));

  function detailFor(item: TodoItem): string | null {
    if (!item.source) return null;
    return reviewItemSourceDetail(item.source, titleById.get(item.source.node_id) ?? item.source.node_id);
  }

  const COLLAPSE_KEY = "reviewItems";
  const COLLAPSE_DEFAULT = true;
  const expanded = $derived(railSectionCollapse.isExpanded(COLLAPSE_KEY, COLLAPSE_DEFAULT));

  // Propose (ADR-0090 §4): the same prompt-offer resolution ConversationsPanel's
  // ＋New menu uses, scoped to THIS entry's own type — identical for every row,
  // since Propose always opens on this entry, never on a row's source.
  let ctx = $derived<PromptResolutionContext>({
    metadataSchema: $metadataSchemaStore,
    promptEntries,
    loreEntries: [],
    availableScenes: [],
    hiddenPromptIds: $hiddenLibraryStore,
  });
  let proposePrompts = $derived(promptEntriesOfferedOn(ctx, subjectEntryType));
  let proposeMenu = $derived(buildPromptMenuTree(proposePrompts));

  // ADR-0091 §4: Propose opens straight on the built-in "Follow a change" when
  // it is offered — found by title, project-owned shadowing the Library's
  // (`proposeDefaultPrompt`). The tile keeps the menu button too whenever more
  // than the default is offered, so the writer can still reach another prompt.
  let defaultPrompt = $derived(proposeDefaultPrompt(proposePrompts));
  let showMenuButton = $derived(!defaultPrompt || proposePrompts.length > 1);

  // One popover open at a time; each row's trigger button is keyed by item id
  // so the popover (a DOM sibling of the button that opened it, per
  // Popover.svelte's in-flow anchoring) drops from the right row.
  let openItemId = $state<string | null>(null);
  let triggerEls = $state<Record<string, HTMLButtonElement | null>>({});

  async function pickPrompt(item: TodoItem, prompt: PromptEntrySummary): Promise<void> {
    openItemId = null;
    const seededInputs = seedConversationInputs(
      prompt,
      nodeId,
      nodeTitle,
      subjectEntryType,
      asOfScene ? { id: asOfScene, title: asOfSceneTitle } : null,
    );
    await todoActions.proposeFromReviewItem(item, prompt, seededInputs, { subjectTitle: nodeTitle });
  }
</script>

<section class="review-items" aria-label={`Review items for ${nodeTitle}`}>
  <RailSectionHeader
    title="Review items"
    glyph="ti-list-check"
    count={items.length}
    {expanded}
    onToggle={() => railSectionCollapse.toggle(COLLAPSE_KEY, COLLAPSE_DEFAULT)}
  />
  {#if expanded}
    <div class="review-items-list">
      <NodeList isEmpty={items.length === 0}>
        {#snippet whenEmpty()}
          <p class="muted">No open review items.</p>
        {/snippet}
        {#each items as item (item.id)}
          <NodeRow
            title={item.text}
            detail={detailFor(item)}
            onClick={() => void todoActions.openFileTodo(item)}
          >
            {#snippet trailing()}
              <div class="ri-propose-anchor">
                {#if defaultPrompt}
                  <!-- ADR-0091 §4: the primary opens the default straight away —
                       no popover — matching NodeRow's plain trailing-button
                       idiom for a direct action. -->
                  <button
                    type="button"
                    title={`Propose with ${defaultPrompt.title}`}
                    aria-label={`Propose a follow-up for ${item.text}`}
                    onmousedown={(event) => event.stopPropagation()}
                    onclick={(event) => {
                      event.stopPropagation();
                      void pickPrompt(item, defaultPrompt);
                    }}
                  ><i class="ti ti-message-plus" aria-hidden="true"></i></button>
                {/if}
                {#if showMenuButton}
                  <button
                    type="button"
                    bind:this={triggerEls[item.id]}
                    class={defaultPrompt ? "row-action-add" : undefined}
                    title={defaultPrompt
                      ? "Other prompts…"
                      : proposePrompts.length > 0
                        ? "Propose…"
                        : "No prompt is offered on this type"}
                    aria-label={defaultPrompt
                      ? `Other prompts for ${item.text}`
                      : `Propose a follow-up for ${item.text}`}
                    aria-haspopup="menu"
                    aria-expanded={openItemId === item.id}
                    disabled={!defaultPrompt && proposePrompts.length === 0}
                    onmousedown={(event) => event.stopPropagation()}
                    onclick={(event) => {
                      event.stopPropagation();
                      openItemId = openItemId === item.id ? null : item.id;
                    }}
                  ><i class={defaultPrompt ? "ti ti-dots-vertical" : "ti ti-message-plus"} aria-hidden="true"></i></button>
                {/if}
                {#if showMenuButton && proposePrompts.length > 0}
                  <Popover
                    open={openItemId === item.id}
                    triggerEl={triggerEls[item.id] ?? null}
                    onClose={() => {
                      if (openItemId === item.id) openItemId = null;
                    }}
                    role="menu"
                    id={`review-item-propose-${item.id}`}
                    label="Propose a follow-up"
                    offset={6}
                    anchor="right"
                    minWidth="200px"
                    maxWidth="320px"
                  >
                    <PromptMenu nodes={proposeMenu} onSelect={(prompt) => void pickPrompt(item, prompt)} />
                  </Popover>
                {/if}
              </div>
            {/snippet}
          </NodeRow>
        {/each}
      </NodeList>
    </div>
  {/if}
</section>

<style>
  .review-items {
    padding-top: 8px;
  }

  /* Tier panel behind the rows — matches ConversationsPanel/BacklinksPanel's
     grouped-children tint so this reads as one grouped surface. */
  .review-items-list {
    padding: 8px;
    background: var(--tier1);
    border-radius: 10px;
  }

  /* The Propose popover's in-flow anchor — a Popover panel positions itself
     absolutely against its nearest `position: relative` ancestor. */
  .ri-propose-anchor {
    position: relative;
    display: inline-flex;
  }

  .muted {
    margin: 0;
    padding: 2px 4px;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
</style>
