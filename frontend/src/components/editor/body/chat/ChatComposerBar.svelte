<!--
  The chat composer strip: the prompt-picker chip, the assistant-picker chip,
  and the Context door — extracted from ChatBodyView (#1086) to keep that view
  under the size cap. Pure picker UI: it owns the open/search/anchor state and
  (for the assistant picker, Context door, and doorway) the shared
  outside-click dismissal, but the two *pick* gestures mutate the parent's
  session state (and persist), so they surface as `onPickPrompt` /
  `onPickAssistant` callbacks — same idiom as ChatInputsStrip's `onDraftChange`.

  ADR-0076 S2: the 👁 preview popover became the worded, drillable **Context**
  door — the one place that answers "what will the AI see". It absorbed the
  post-lock inputs strip ("Inputs (locked)") and the journal-scope strip
  ("Auto-added this conversation"); each lore tier now expands to its member
  entries by title. Preview honesty (#1477) was fixed at the source (the
  backend threads the send path's actual selection, not a static scan) — this
  component only renders what it's given.

  ADR-0076 S5: the prompt chip's hand-rolled flat dropdown became the shared
  `Popover` + `PromptMenu` `/`-tree drill (same idiom as ConversationsPanel's
  ＋New menu) — the picker loses its search field; the assistant picker (its
  own search + soft partition) is untouched, only its chip glyph changed.
-->
<script lang="ts">
  import { onMount, tick } from "svelte";
  import { assistantTitle, partitionAssistants } from "@/lib/chat/assistantScope";
  import { formatTokens } from "@/lib/utils/money";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import Popover from "@/components/chrome/Popover.svelte";
  import PromptMenu from "@/components/editor/PromptMenu.svelte";
  import { buildPromptMenuTree } from "@/lib/editor-core/promptMenuTree";
  import type {
    AssistantEntrySummary,
    ChatSessionJournalEntry,
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
    // ADR-0057 §2: whether the bound prompt's `use_lore()`/`use()` gate ran —
    // the Context door's System section annotates it (not a call-site marker;
    // see ADR-0076 decision 9's rejected alternative).
    loreEnabled: boolean;
    // The chat's auto-detected context journal (ADR-0075) — the Context door's
    // "Auto-added this conversation" section; the transcript already stamps
    // per-turn `journal_added` chips, so this is the running roster.
    journal: ChatSessionJournalEntry[];
    // Locked-chat filled input values, already titled for display (ChatBodyView
    // resolves them via chatInputs.ts's displayInputValues). Empty pre-lock —
    // the inputs strip is the form then, not telemetry. `name` is the row key
    // (unique, unlike the authored label).
    lockedInputDisplays: { name: string; label: string; value: string }[];
    // id → title, for a tier's member entries and the locked-inputs display.
    titleFor: (id: string) => string | null;
    onPickPrompt: (entry: PromptEntrySummary) => void;
    onPickAssistant: (id: string) => void;
    // ADR-0076 S4: the lock doorway's one action — create a fresh chat seeded
    // with the same prompt/assistant/input drafts (never the transcript).
    onNewChatWithSetup: () => void;
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
    loreEnabled,
    journal,
    lockedInputDisplays,
    titleFor,
    onPickPrompt,
    onPickAssistant,
    onNewChatWithSetup,
  }: Props = $props();

  // Cache blocks that carry text — the readable system + lore the model sees.
  const previewBlocksWithText = $derived(
    (previewCacheBlocks ?? []).filter((b) => b.text && b.text.trim()),
  );
  // The system block is singled out (label "system") for its own section,
  // annotated with the lore gate. The SYSTEM block also carries `tier:
  // "stable"` (it caches with the stable prefix), so the tier partition
  // below must exclude it by label — `tier` alone doesn't separate them.
  const systemBlock = $derived(previewBlocksWithText.find((b) => b.label === "system"));
  // Each tier drills down to its member entries by title (ADR-0076 decision 2).
  const tierBlocks = $derived(previewBlocksWithText.filter((b) => b.tier && b.label !== "system"));
  // Everything else (conversation turns carried in the send-path composition)
  // keeps rendering as today's labeled sections — untouched by this slice.
  const otherBlocks = $derived(previewBlocksWithText.filter((b) => !b.tier));

  // ---- prompt-picker UI state (composer chip → PromptMenu's `/`-tree drill,
  // ADR-0076 S5 — mirrors ConversationsPanel's ＋New menu; Popover owns its
  // own click-outside + Escape dismissal) ----
  let promptMenuOpen = $state(false);
  const promptMenu = $derived(buildPromptMenuTree(routedPromptEntries));
  let promptPickerBtnEl: HTMLButtonElement | null = $state(null);

  // ---- assistant-picker UI state (mirrors prompt picker; replaces native <select>) ----
  let assistantPickerOpen = $state(false);
  let assistantPickerSearch = $state("");
  let assistantPickerEl: HTMLDivElement | null = $state(null);
  let assistantPickerBtnEl: HTMLButtonElement | null = $state(null);

  // ---- Context door popover state ----
  let chatPreviewPopoverOpen = $state(false);
  let chatPreviewBtnEl: HTMLButtonElement | null = $state(null);
  let chatPreviewPopoverEl: HTMLDivElement | null = $state(null);

  // ---- ADR-0076 S4: the lock doorway popover state ----
  // A locked chip is inert by default (tooltip only); once a prompt is bound
  // it becomes a doorway to a fresh chat with the same setup (decision 8).
  let doorwayOpen: "" | "prompt" | "assistant" = $state("");
  let doorwayPopoverEl: HTMLDivElement | null = $state(null);
  // The doorway is only honest when its action can actually run: "New chat with
  // this setup" reuses the bound prompt, so gate on the prompt RESOLVING in the
  // same roster ChatBodyView's activePromptEntry uses — a bound id that no longer
  // resolves (a deleted prompt) must not offer a button that silently no-ops.
  const canDoorway = $derived(isLocked && promptEntries.some((p) => p.id === chatPromptEntryId));
  function openDoorway(which: "prompt" | "assistant") {
    // Mutually exclusive with the pickers + Context door.
    promptMenuOpen = false;
    assistantPickerOpen = false;
    chatPreviewPopoverOpen = false;
    doorwayOpen = which;
  }
  function closeDoorway() {
    doorwayOpen = "";
  }

  let assistantParts = $derived(partitionAssistants(assistantEntries, assistantPickerSearch, assistantScope));

  function promptTitle(promptId: string): string {
    if (!promptId) return "Pick a prompt";
    const entry = promptEntries.find((p) => p.id === promptId);
    return entry?.title ?? "Unknown prompt";
  }

  function pickPrompt(entry: PromptEntrySummary): void {
    promptMenuOpen = false;
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

  // Shared outside-click dismissal. The prompt picker's Popover owns its own
  // click-outside + Escape dismissal (ADR-0076 S5) — only the assistant
  // picker, Context door, and doorway route through this handler now.
  function handleDocumentClick(event: MouseEvent) {
    const target = event.target as Node;
    if (assistantPickerOpen) {
      const insidePicker = assistantPickerEl?.contains(target) || assistantPickerBtnEl?.contains(target);
      if (!insidePicker) closeAssistantPicker();
    }
    if (chatPreviewPopoverOpen) {
      const insidePreview = chatPreviewPopoverEl?.contains(target) || chatPreviewBtnEl?.contains(target);
      if (!insidePreview) chatPreviewPopoverOpen = false;
    }
    if (doorwayOpen) {
      const anchorBtn = doorwayOpen === "prompt" ? promptPickerBtnEl : assistantPickerBtnEl;
      const inside = doorwayPopoverEl?.contains(target) || anchorBtn?.contains(target);
      if (!inside) doorwayOpen = "";
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
      onclick={() => (canDoorway ? openDoorway("prompt") : (promptMenuOpen = !promptMenuOpen))}
      disabled={isLocked && !chatPromptEntryId}
      aria-expanded={promptMenuOpen || doorwayOpen === "prompt"}
    >
      <i class="cbv-chip-glyph ti ti-sparkles" aria-hidden="true"></i>
      <strong>{promptTitle(chatPromptEntryId)}</strong>
      {#if isLocked}
        <i class="cbv-chip-lock ti ti-lock" aria-label="locked"></i>
      {:else}
        <GroupCaret size="xs" />
      {/if}
    </button>
    <Popover
      bind:open={promptMenuOpen}
      triggerEl={promptPickerBtnEl}
      role="menu"
      anchor="left"
      offset={6}
      minWidth="200px"
      maxWidth="320px"
    >
      <PromptMenu nodes={promptMenu} onSelect={(entry) => pickPrompt(entry)} />
    </Popover>
    {#if doorwayOpen === "prompt"}
      {@render doorway("Locked after the first message — this prompt shapes every turn.")}
    {/if}
  </div>
  <div class="cbv-prompt-anchor">
    <button
      type="button"
      class="cbv-chip cbv-chip-button cbv-chip-graphite"
      class:cbv-chip-locked={isLocked}
      title={isLocked ? "Assistant is locked while this chat has messages." : "Pick an assistant"}
      bind:this={assistantPickerBtnEl}
      onclick={() => (canDoorway ? openDoorway("assistant") : void toggleAssistantPicker())}
      disabled={isLocked && !chatPromptEntryId}
      aria-label="Assistant"
      aria-expanded={doorwayOpen === "assistant"}
    >
      <i class="cbv-chip-glyph ti ti-robot" aria-hidden="true"></i>
      <strong>{assistantTitle(chatAssistantId, assistantEntries, scopedDefaultId)}</strong>
      {#if isLocked}
        <i class="cbv-chip-lock ti ti-lock" aria-label="locked"></i>
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
    {#if doorwayOpen === "assistant"}
      {@render doorway("Locked after the first message — this assistant answers every turn.")}
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
  {#snippet doorway(message: string)}
    <div
      class="cbv-doorway-popover"
      role="dialog"
      aria-label="Locked — start fresh"
      bind:this={doorwayPopoverEl}
    >
      <p class="cbv-doorway-note">{message}</p>
      <button
        type="button"
        class="cbv-doorway-action"
        onclick={() => {
          onNewChatWithSetup();
          closeDoorway();
        }}
      >
        New chat with this setup
      </button>
    </div>
  {/snippet}
  <div class="cbv-preview-anchor">
    <button
      type="button"
      class="cbv-preview-btn"
      class:cbv-preview-btn-active={chatPreviewPopoverOpen}
      bind:this={chatPreviewBtnEl}
      title="Context — what will be sent"
      aria-label="Context — what will be sent"
      aria-expanded={chatPreviewPopoverOpen}
      onclick={toggleChatPreviewPopover}
    >Context</button>
    {#if chatPreviewPopoverOpen}
      <div
        class="cbv-preview-popover"
        role="dialog"
        aria-label="Context — what will be sent"
        bind:this={chatPreviewPopoverEl}
      >
        <header class="cbv-preview-popover-header">
          <strong>Context</strong>
          <small>what the AI will see, drillable</small>
          <button
            type="button"
            class="cbv-preview-popover-close"
            aria-label="Close"
            onclick={() => (chatPreviewPopoverOpen = false)}
          >×</button>
        </header>
        <div class="cbv-preview-popover-body">
          <!-- a. System — the gate annotation (not a call-site marker; ADR-0076
               decision 9's rejected alternative) then the system text, sourced
               from the send-path block when present, else the same fallback
               chain this popover always had. -->
          <section class="cbv-ctx-section">
            <span class="cbv-ctx-caps">System</span>
            {#if loreEnabled}
              <div
                class="cbv-ctx-kv-line"
                title="The template invoked use_lore()/use() — the send path selects and attaches lore; the tiers below are where it lands."
              ><strong>lore-enabled</strong> · by this prompt</div>
            {/if}
            {#if systemBlock}
              <pre class="cbv-preview-content">{systemBlock.text}</pre>
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
          </section>

          <!-- b. Tiers — each lore tier drills down to its member entries by
               title (ADR-0076 decision 2). The lore text stays reachable here
               too: it lives ONLY in this block, never the rendered template. -->
          {#each tierBlocks as block (block.label)}
            <details class="cbv-ctx-tier">
              <summary>
                <GroupCaret size="xs" ambient />
                <span class="cbv-ctx-caps">{block.label}</span>
                <span class="cbv-ctx-kv">
                  {#if block.entry_ids && block.entry_ids.length > 0}<strong>{block.entry_ids.length} {block.entry_ids.length === 1 ? "entry" : "entries"}</strong> · {/if}{formatTokens(block.tokens)} tok · cached ({block.tier})
                </span>
              </summary>
              {#if block.entry_ids && block.entry_ids.length > 0}
                <ul class="cbv-ctx-tier-entries">
                  {#each block.entry_ids as id (id)}
                    <li>{titleFor(id) ?? id}</li>
                  {/each}
                </ul>
              {/if}
              <pre class="cbv-preview-content">{block.text}</pre>
            </details>
          {/each}

          <!-- Non-tier, non-system blocks (conversation turns) keep rendering
               as today's labeled sections. -->
          {#each otherBlocks as block}
            <div class="cbv-preview-message">
              <header class="cbv-preview-msg-role">{block.label}</header>
              <pre class="cbv-preview-content">{block.text}</pre>
            </div>
          {/each}

          <!-- c. Inputs (locked) — read-only, once the chat has locked its
               prompt/assistant/inputs. Pre-lock the inputs strip IS the form. -->
          {#if lockedInputDisplays.length > 0}
            <section class="cbv-ctx-section">
              <span class="cbv-ctx-caps">Inputs (locked)</span>
              <!-- Keyed by input NAME — labels are author-authored and can
                   collide, and a duplicate key is a hard Svelte error. -->
              {#each lockedInputDisplays as pair (pair.name)}
                <div class="cbv-ctx-kv-line"><strong>{pair.label}</strong> · <span class="cbv-ctx-value">{pair.value}</span></div>
              {/each}
            </section>
          {/if}

          <!-- d. Auto-added this conversation — the running journal roster; the
               transcript already stamps per-turn journal_added chips, this is
               the door's account of the whole conversation so far. -->
          {#if journal.length > 0}
            <section class="cbv-ctx-section">
              <span class="cbv-ctx-caps">Auto-added this conversation</span>
              {#each journal as entry (entry.entry_id)}
                <div class="cbv-ctx-kv-line">
                  {entry.title || entry.entry_id}{#if entry.added_at_turn != null} · turn {entry.added_at_turn}{/if}{#if entry.source === "depth1_expansion"} · ↳ depth 1{/if}
                </div>
              {/each}
            </section>
          {/if}

          <p class="cbv-meta cbv-preview-hint">
            This is the system message and context the assistant receives on the next turn.
            Chat history above is also sent. Composer text becomes the next user message —
            anything it newly mentions is auto-detected and joins the context at send.
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

  /* ADR-0076 S4: the lock doorway — a locked chip's popover. One line of
     constraint, one worded action; no header, no close × (decision 8). Mirrors
     .cbv-preview-popover's shell, narrower. */
  .cbv-doorway-popover {
    position: absolute; top: 100%; left: 0; margin-top: var(--sp-2); z-index: var(--z-dropdown);
    width: 240px; background: var(--panel); border: 1px solid var(--border-strong);
    border-radius: var(--r-lg); box-shadow: var(--elev-2);
    padding: var(--sp-3); display: flex; flex-direction: column; gap: var(--sp-3);
  }
  .cbv-doorway-note { margin: 0; font-size: var(--fs-sm); color: var(--text-2); line-height: 1.4; }
  .cbv-doorway-action {
    /* The §4 `sm` recipe (--fs-xs on --sp-0/--sp-2, --r-md), outline variant —
       the door's one standalone action. */
    align-self: flex-start; padding: var(--sp-0) var(--sp-2); font-size: var(--fs-xs); font-weight: 600;
    border: 1px solid var(--border-strong); border-radius: var(--r-md); background: transparent;
    color: var(--text); cursor: pointer;
  }
  .cbv-doorway-action:hover { background: var(--inset); }

  /* Assistant chip = graphite variant of .cbv-chip. Trigger + popover
     mirror the prompt picker exactly so both read at the same height
     and the dropdown renders NodeRow-style entries. */
  .cbv-chip-graphite {
    background: var(--k-graphite-soft);
    border-color: var(--k-graphite);
    color: var(--k-graphite-text);
  }
  .cbv-chip-graphite strong { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* The Context door (ADR-0076 decision 9): a worded, not glyph, button — the
     lexicon has no agreed icon for "the payload account" and the eye is
     reserved for interiority (ADR-0070). Mirrors the mockup's .btn-preview. */
  .cbv-preview-anchor { position: relative; display: inline-flex; align-items: center; margin-left: auto; }
  .cbv-preview-btn {
    /* The §4 `sm` button recipe: --fs-xs on --sp-0/--sp-2 padding, --r-md. */
    padding: var(--sp-0) var(--sp-2); font-size: var(--fs-xs); font-weight: 600;
    border: none; border-radius: var(--r-md); background: transparent;
    color: var(--text-3); cursor: pointer;
  }
  .cbv-preview-btn:hover { background: var(--inset); color: var(--text-2); }
  .cbv-preview-btn-active { background: var(--accent-soft); color: var(--accent-emphasis); }

  /* The door's popover shell — the §4 popover contract: --panel at --elev-2,
     --r-lg, on the dropdown z-layer. (Conformed in S2: the old shell kept a
     private palette — --surface, 12px, a hand-rolled shadow, z-index 40.) */
  .cbv-preview-popover {
    position: absolute; top: 100%; right: 0; margin-top: var(--sp-2); z-index: var(--z-dropdown);
    width: 380px; max-height: 60vh; background: var(--panel);
    border: 1px solid var(--border-strong); border-radius: var(--r-lg);
    box-shadow: var(--elev-2); display: flex; flex-direction: column; overflow: hidden;
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

  /* ADR-0076 S2: the Context door's labeled sections (System / Inputs
     (locked) / Auto-added this conversation) — the house caps-label recipe,
     spacing on the --sp scale throughout. */
  .cbv-ctx-section { margin-bottom: var(--sp-3); }
  .cbv-ctx-section:last-child { margin-bottom: 0; }
  .cbv-ctx-caps {
    font-size: var(--fs-xs); font-weight: 600; letter-spacing: 0.07em;
    text-transform: uppercase; color: var(--text-3);
  }
  .cbv-ctx-kv-line {
    display: flex; gap: var(--sp-1); flex-wrap: wrap;
    font-size: var(--fs-sm); color: var(--text-2); margin-top: var(--sp-1);
  }
  .cbv-ctx-kv-line strong { font-weight: 600; color: var(--text); }
  .cbv-ctx-value { color: var(--text-2); }

  /* A tier's <details>: the GroupCaret + <summary> idiom (mirrors
     ChatTranscript's thinking accordion) — expands to the member entries by
     title, then the block's own text (the lore lives only here). */
  .cbv-ctx-tier { margin-bottom: var(--sp-3); }
  .cbv-ctx-tier summary {
    display: flex; align-items: center; gap: var(--sp-2); cursor: pointer; list-style: none;
    --group-caret-open: 0deg;
  }
  .cbv-ctx-tier summary::-webkit-details-marker { display: none; }
  .cbv-ctx-tier[open] summary { --group-caret-open: 90deg; }
  .cbv-ctx-kv { font-size: var(--fs-sm); color: var(--text-2); margin-left: var(--sp-1); }
  .cbv-ctx-kv strong { font-weight: 600; color: var(--text); }
  .cbv-ctx-tier-entries {
    margin: var(--sp-1) 0 0; padding: var(--sp-0) 0 var(--sp-0) var(--sp-3); list-style: none;
    font-size: var(--fs-sm); color: var(--text-2);
    border-left: 2px solid var(--divider);
  }
  .cbv-ctx-tier-entries li { padding: var(--sp-0) 0; }
</style>
