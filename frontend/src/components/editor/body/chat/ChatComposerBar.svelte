<!--
  The chat composer strip: the prompt-picker chip, the assistant-picker chip,
  and the 👁 preview popover — extracted from ChatBodyView (#1086) to keep that
  view under the size cap. Pure picker UI: it owns the open/search/anchor state
  and the shared outside-click dismissal, but the two *pick* gestures mutate the
  parent's session state (and persist), so they surface as `onPickPrompt` /
  `onPickAssistant` callbacks — same idiom as ChatInputsStrip's `onDraftChange`.
-->
<script lang="ts">
  import { onMount, tick } from "svelte";
  import { assistantTitle, partitionAssistants } from "@/lib/chat/assistantScope";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import type {
    AssistantEntrySummary,
    PreviewCacheBlock,
    PreviewMessage,
    PromptEntrySummary,
  } from "@/lib/types";

  interface Props {
    // A chat with messages locks its prompt + assistant (they repeat every turn).
    isLocked: boolean;
    chatPromptEntryId: string;
    chatAssistantId: string;
    // Full roster — so the bound prompt's title resolves even when it isn't in
    // the (routed, filtered) pick list.
    promptEntries: PromptEntrySummary[];
    // The chat-routed pick list (conversation prompts, brainstorms excluded).
    routedPromptEntries: PromptEntrySummary[];
    assistantEntries: AssistantEntrySummary[];
    // The bound prompt's assistant tag-scope (ADR-0024) — drives the soft
    // partition of the assistant roster into matching / rest.
    assistantScope: string[];
    scopedDefaultId: string;
    // Post-send: the locked system message. Pre-send: the assembled preview.
    chatSystemPrompt: string;
    chatPreviewMessages: PreviewMessage[] | null;
    // The send-path cache blocks (system prompt + attached lore tiers) with their
    // text — what the model ACTUALLY receives next turn. The `use_lore()` gate
    // emits nothing into the template, so the lore lives only here, not in
    // `chatSystemPrompt`/`chatPreviewMessages`; the preview must render it or it
    // looks empty (#1546 follow-up).
    previewCacheBlocks: PreviewCacheBlock[];
    onPickPrompt: (entry: PromptEntrySummary) => void;
    onPickAssistant: (id: string) => void;
  }

  let {
    isLocked,
    chatPromptEntryId,
    chatAssistantId,
    promptEntries,
    routedPromptEntries,
    assistantEntries,
    assistantScope,
    scopedDefaultId,
    chatSystemPrompt,
    chatPreviewMessages,
    previewCacheBlocks,
    onPickPrompt,
    onPickAssistant,
  }: Props = $props();

  // Cache blocks that carry text — the readable system + lore the model sees.
  const previewBlocksWithText = $derived(
    (previewCacheBlocks ?? []).filter((b) => b.text && b.text.trim()),
  );

  // ---- prompt-picker UI state (composer chip → dropdown) ----
  let promptPickerOpen = $state(false);
  let promptPickerSearch = $state("");
  let promptPickerEl: HTMLDivElement | null = $state(null);
  let promptPickerBtnEl: HTMLButtonElement | null = $state(null);

  // ---- assistant-picker UI state (mirrors prompt picker; replaces native <select>) ----
  let assistantPickerOpen = $state(false);
  let assistantPickerSearch = $state("");
  let assistantPickerEl: HTMLDivElement | null = $state(null);
  let assistantPickerBtnEl: HTMLButtonElement | null = $state(null);

  // ---- 👁 preview popover state ----
  let chatPreviewPopoverOpen = $state(false);
  let chatPreviewBtnEl: HTMLButtonElement | null = $state(null);
  let chatPreviewPopoverEl: HTMLDivElement | null = $state(null);

  let assistantParts = $derived(partitionAssistants(assistantEntries, assistantPickerSearch, assistantScope));

  function promptTitle(promptId: string): string {
    if (!promptId) return "Pick a prompt";
    const entry = promptEntries.find((p) => p.id === promptId);
    return entry?.title ?? "Unknown prompt";
  }

  function filteredChatPromptEntries(): PromptEntrySummary[] {
    const q = promptPickerSearch.trim().toLowerCase();
    const sorter = (a: PromptEntrySummary, b: PromptEntrySummary) =>
      a.title.localeCompare(b.title, undefined, { sensitivity: "base" });
    if (!q) return routedPromptEntries.slice().sort(sorter);
    return routedPromptEntries
      .filter((e) => e.title.toLowerCase().includes(q) || (e.entry_type || "").toLowerCase().includes(q))
      .sort(sorter);
  }

  async function toggleChatPromptPicker() {
    if (isLocked) return;
    promptPickerOpen = !promptPickerOpen;
    promptPickerSearch = "";
    if (promptPickerOpen) {
      await tick();
      const input = promptPickerEl?.querySelector<HTMLInputElement>(".cbv-picker-search");
      input?.focus();
    }
  }

  function closeChatPromptPicker() {
    promptPickerOpen = false;
    promptPickerSearch = "";
  }

  function pickPrompt(entry: PromptEntrySummary): void {
    closeChatPromptPicker();
    onPickPrompt(entry);
  }

  async function toggleAssistantPicker() {
    if (isLocked) return;
    assistantPickerOpen = !assistantPickerOpen;
    assistantPickerSearch = "";
    if (assistantPickerOpen) {
      await tick();
      const input = assistantPickerEl?.querySelector<HTMLInputElement>(".cbv-picker-search");
      input?.focus();
    }
  }

  function closeAssistantPicker() {
    assistantPickerOpen = false;
    assistantPickerSearch = "";
  }

  function pickAssistant(id: string): void {
    closeAssistantPicker();
    onPickAssistant(id);
  }

  function toggleChatPreviewPopover() {
    chatPreviewPopoverOpen = !chatPreviewPopoverOpen;
  }

  // Shared outside-click dismissal for all three menus.
  function handleDocumentClick(event: MouseEvent) {
    const target = event.target as Node;
    if (promptPickerOpen) {
      const insidePicker = promptPickerEl?.contains(target) || promptPickerBtnEl?.contains(target);
      if (!insidePicker) closeChatPromptPicker();
    }
    if (assistantPickerOpen) {
      const insidePicker = assistantPickerEl?.contains(target) || assistantPickerBtnEl?.contains(target);
      if (!insidePicker) closeAssistantPicker();
    }
    if (chatPreviewPopoverOpen) {
      const insidePreview = chatPreviewPopoverEl?.contains(target) || chatPreviewBtnEl?.contains(target);
      if (!insidePreview) chatPreviewPopoverOpen = false;
    }
  }

  onMount(() => {
    document.addEventListener("mousedown", handleDocumentClick);
    return () => document.removeEventListener("mousedown", handleDocumentClick);
  });
</script>

<div class="cbv-composer-strip">
  <div class="cbv-prompt-anchor">
    <button
      type="button"
      class="cbv-chip cbv-chip-button"
      class:cbv-chip-locked={isLocked}
      class:cbv-chip-assigned={!!chatPromptEntryId}
      title={isLocked ? "Prompt is locked while this chat has messages." : "Pick a prompt"}
      bind:this={promptPickerBtnEl}
      onclick={() => void toggleChatPromptPicker()}
      disabled={isLocked && !chatPromptEntryId}
    >
      <span class="cbv-chip-glyph" aria-hidden="true">✨</span>
      <strong>{promptTitle(chatPromptEntryId)}</strong>
      {#if isLocked}
        <span class="cbv-chip-lock" aria-label="locked">🔒</span>
      {:else}
        <GroupCaret size="xs" />
      {/if}
    </button>
    {#if promptPickerOpen}
      <div class="cbv-prompt-picker" role="menu" bind:this={promptPickerEl}>
        <input
          class="cbv-picker-search"
          type="text"
          placeholder="Search prompts…"
          bind:value={promptPickerSearch}
        />
        {#each filteredChatPromptEntries() as entry (entry.id)}
          <button
            type="button"
            class:cbv-picker-active={entry.id === chatPromptEntryId}
            onclick={() => pickPrompt(entry)}
          >
            <strong>{entry.title}</strong>
            <small>{entry.entry_type}</small>
          </button>
        {:else}
          <p class="cbv-picker-empty">
            {promptPickerSearch
              ? "No prompts match."
              : "No chat-routed prompts. Create one with a Chat output (no output handler)."}
          </p>
        {/each}
      </div>
    {/if}
  </div>
  <div class="cbv-prompt-anchor">
    <button
      type="button"
      class="cbv-chip cbv-chip-button cbv-chip-graphite"
      class:cbv-chip-locked={isLocked}
      title={isLocked ? "Assistant is locked while this chat has messages." : "Pick an assistant"}
      bind:this={assistantPickerBtnEl}
      onclick={() => void toggleAssistantPicker()}
      disabled={isLocked}
      aria-label="Assistant"
    >
      <span class="cbv-chip-glyph" aria-hidden="true">🤖</span>
      <strong>{assistantTitle(chatAssistantId, assistantEntries, scopedDefaultId)}</strong>
      {#if isLocked}
        <span class="cbv-chip-lock" aria-label="locked">🔒</span>
      {:else}
        <GroupCaret size="xs" />
      {/if}
    </button>
    {#if assistantPickerOpen}
      <div class="cbv-prompt-picker" role="menu" bind:this={assistantPickerEl}>
        <input
          class="cbv-picker-search"
          type="text"
          placeholder="Search assistants…"
          bind:value={assistantPickerSearch}
        />
        <button
          type="button"
          class:cbv-picker-active={chatAssistantId === ""}
          onclick={() => pickAssistant("")}
        >
          <strong>Default</strong>
          <small>{assistantTitle("", assistantEntries, scopedDefaultId).replace(/^Default \(|\)$/g, "") || "machine default"}</small>
        </button>
        {#if assistantParts.matching.length === 0 && assistantParts.rest.length === 0}
          <p class="cbv-picker-empty">
            {assistantPickerSearch ? "No assistants match." : "No assistants configured."}
          </p>
        {:else}
          {#if assistantParts.matching.length > 0}
            <div class="cbv-picker-group-label">Suggested for this prompt</div>
          {/if}
          {#each assistantParts.matching as assistant (assistant.id)}
            {@render assistantOption(assistant)}
          {/each}
          {#if assistantParts.matching.length > 0 && assistantParts.rest.length > 0}
            <div class="cbv-picker-divider" role="separator"></div>
          {/if}
          {#each assistantParts.rest as assistant (assistant.id)}
            {@render assistantOption(assistant)}
          {/each}
        {/if}
      </div>
    {/if}
  </div>
  {#snippet assistantOption(assistant: AssistantEntrySummary)}
    <button
      type="button"
      class:cbv-picker-active={assistant.id === chatAssistantId}
      onclick={() => pickAssistant(assistant.id)}
    >
      <strong>{assistant.title}</strong>
      <small>{assistant.entry_type}</small>
    </button>
  {/snippet}
  <div class="cbv-preview-anchor">
    <button
      type="button"
      class="cbv-preview-icon"
      class:cbv-preview-icon-active={chatPreviewPopoverOpen}
      bind:this={chatPreviewBtnEl}
      title="Preview what's sent — system message + attached context"
      aria-label="Preview what's sent"
      aria-expanded={chatPreviewPopoverOpen}
      onclick={toggleChatPreviewPopover}
    >👁</button>
    {#if chatPreviewPopoverOpen}
      <div
        class="cbv-preview-popover"
        role="dialog"
        aria-label="Preview what's sent"
        bind:this={chatPreviewPopoverEl}
      >
        <header class="cbv-preview-popover-header">
          <strong>Preview</strong>
          <small>system message + attached context</small>
          <button
            type="button"
            class="cbv-preview-popover-close"
            aria-label="Close"
            onclick={() => (chatPreviewPopoverOpen = false)}
          >×</button>
        </header>
        <div class="cbv-preview-popover-body">
          {#if previewBlocksWithText.length > 0}
            <!-- The real send-path context: the system block(s) AND the attached
                 lore tiers, each labelled. Without this the lore (which lives only
                 in a cache block, never the rendered template) is invisible. -->
            {#each previewBlocksWithText as block}
              <div class="cbv-preview-message">
                <header class="cbv-preview-msg-role">
                  {block.label}{block.tier ? ` · ${block.tier}` : ""}
                </header>
                <pre class="cbv-preview-content">{block.text}</pre>
              </div>
            {/each}
          {:else if chatSystemPrompt && chatSystemPrompt.trim()}
            <pre class="cbv-preview-content">{chatSystemPrompt}</pre>
          {:else if chatPreviewMessages && chatPreviewMessages.length > 0}
            {#each chatPreviewMessages as message}
              <div class="cbv-preview-message">
                <header class="cbv-preview-msg-role">{message.role}</header>
                {#each message.blocks as block}
                  <pre class="cbv-preview-content">{block.text}</pre>
                {/each}
              </div>
            {/each}
          {:else if chatPromptEntryId}
            <p class="cbv-meta">
              Fill the required inputs above and the assembled message will appear here.
            </p>
          {:else}
            <p class="cbv-meta">No system message will be sent. The model sees only the chat history.</p>
          {/if}
          <p class="cbv-meta cbv-preview-hint">
            This is the system message and context the assistant receives on the next turn.
            Chat history above is also sent. Composer text becomes the next user message.
          </p>
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  /* The strip sits as a natural-height flex child of .chat-body-view. */
  .cbv-composer-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding-bottom: 11px;
    border-bottom: 1px solid var(--divider);
    flex: 0 0 auto;
  }
  .cbv-chip {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 5px 11px;
    border-radius: 999px;
    background: var(--surface);
    border: 1px solid var(--border);
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-2);
  }
  /* Prompt chip = brown (snippet) StatusPill once bound. */
  .cbv-chip-assigned {
    background: var(--k-snippet-soft);
    border-color: var(--k-snippet);
    color: var(--k-snippet-text);
  }
  .cbv-chip strong { font-weight: 600; }
  .cbv-chip-glyph { font-size: var(--fs-md); }
  .cbv-chip-lock { font-size: var(--fs-xs); opacity: 0.65; }
  .cbv-chip-locked { opacity: 0.8; }
  .cbv-chip-button { cursor: pointer; font: inherit; }
  .cbv-chip-button[disabled] { cursor: default; }

  .cbv-prompt-anchor { position: relative; display: inline-flex; align-items: center; gap: 4px; }

  .cbv-prompt-picker {
    position: absolute; top: 100%; left: 0; margin-top: 6px; z-index: 30;
    background: var(--surface); border: 1px solid var(--border-strong);
    border-radius: 11px; box-shadow: 0 12px 30px var(--shadow2);
    padding: 6px; min-width: 250px; max-height: 320px; overflow-y: auto;
    display: flex; flex-direction: column; gap: 2px;
  }
  .cbv-picker-search {
    width: 100%; box-sizing: border-box; padding: 6px 8px; border-radius: 7px;
    border: 1px solid var(--border); font-size: var(--fs-md); margin-bottom: 4px;
  }
  .cbv-prompt-picker > button {
    text-align: left; padding: 7px 9px; border-radius: 8px;
    border: 1px solid transparent; background: transparent; cursor: pointer;
    display: flex; flex-direction: column; gap: 2px;
  }
  .cbv-prompt-picker > button:hover { background: var(--inset); }
  .cbv-prompt-picker > button.cbv-picker-active {
    background: var(--accent-soft); border-color: var(--accent-soft2);
  }
  .cbv-prompt-picker > button > strong { font-weight: 600; font-size: var(--fs-md); }
  .cbv-prompt-picker > button > small { font-size: var(--fs-xs); color: var(--text-3); }
  .cbv-picker-empty { margin: 4px 6px; font-size: var(--fs-sm); color: var(--text-3); }

  /* Soft-partition affordances (ADR-0024): a label over the matching group and
     a hairline before the rest of the roster. */
  .cbv-picker-group-label {
    padding: 4px 8px 2px;
    font-size: var(--fs-xs);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-3);
  }

  .cbv-picker-divider {
    height: 1px;
    margin: 5px 6px;
    background: var(--border);
  }

  /* Assistant chip = graphite variant of .cbv-chip. Trigger + popover
     mirror the prompt picker exactly so both read at the same height
     and the dropdown renders NodeRow-style entries. */
  .cbv-chip-graphite {
    background: var(--k-graphite-soft);
    border-color: var(--k-graphite);
    color: var(--k-graphite-text);
  }
  .cbv-chip-graphite strong { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* 👁 preview icon button. */
  .cbv-preview-anchor { position: relative; display: inline-flex; align-items: center; margin-left: auto; }
  .cbv-preview-icon {
    width: 30px; height: 30px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--surface);
    cursor: pointer; font-size: var(--fs-lg); line-height: 1; padding: 0; color: var(--text-2);
  }
  .cbv-preview-icon:hover { background: var(--inset); }
  .cbv-preview-icon-active { background: var(--accent-soft); border-color: var(--accent-soft2); }

  /* Preview popover. */
  .cbv-preview-popover {
    position: absolute; top: 100%; right: 0; margin-top: 6px; z-index: 40;
    width: 380px; max-height: 60vh; background: var(--surface);
    border: 1px solid var(--border-strong); border-radius: 12px;
    box-shadow: 0 12px 30px var(--shadow2); display: flex; flex-direction: column; overflow: hidden;
  }
  .cbv-preview-popover-header {
    display: flex; align-items: baseline; gap: 8px; padding: 9px 13px;
    border-bottom: 1px solid var(--divider); background: var(--panel); font-size: var(--fs-sm);
  }
  .cbv-preview-popover-header strong { font-size: var(--fs-sm); font-weight: 600; color: var(--text); }
  .cbv-preview-popover-header small { color: var(--text-3); flex: 1; font-size: var(--fs-xs); }
  .cbv-preview-popover-close {
    background: transparent; border: none; cursor: pointer; font-size: var(--fs-lg);
    line-height: 1; padding: 0 2px; color: var(--text-3);
  }
  .cbv-preview-popover-body { padding: 12px 14px; overflow-y: auto; flex: 1; }
  .cbv-preview-content {
    margin: 0 0 8px; font-family: var(--mono);
    font-size: var(--fs-sm); line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; color: var(--text);
  }
  .cbv-preview-message { margin-bottom: 10px; }
  .cbv-preview-msg-role {
    font-size: var(--fs-xs); font-weight: 600; letter-spacing: 0.07em;
    text-transform: uppercase; color: var(--text-3); margin-bottom: 3px;
  }
  /* Local copy of .cbv-meta — the popover's notes use it (the parent's scoped
     rule doesn't reach this child's markup). */
  .cbv-meta { margin: 0; font-size: var(--fs-sm); color: var(--text-3); }
  .cbv-preview-hint { font-style: italic; }
</style>
