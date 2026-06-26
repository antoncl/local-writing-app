<!--
  ChatBodyView — body-region slot for entry types whose body_shape is
  "chat". Owns its own ChatSession state.

  Phases shipped here:
    4a — skeleton + body-shape routing
    4b — read-only fetch via /api/nodes/{id} + composer chips + messages
    4c-send — message input, send/stream, persist via unified PUT

  Still deferred (Phase 4c-rest):
    - Preview popover (rendered system + attached context)
    - Inputs strip (declared prompt inputs) + first-send template render
    - Journal scope strip + cost-estimate + TTL strips
    - Body-spec visual pass (10-region layout)

  Until Phase 4d switches the editor-pane open-chat flow, this view is
  reachable only through the `details.dev-chat-body-view-mount` panel
  in App.svelte's chat pane (used to compare unified vs bespoke).
-->
<script lang="ts">
  import { createEventDispatcher, onMount, tick } from "svelte";
  import { api } from "./api";
  import PlainTextEditor from "./PlainTextEditor.svelte";
  import { renderChatContent } from "./chatMessageRender";
  import { formatCostEur } from "./money";
  import type {
    AssistantEntrySummary,
    ChatMessage,
    ChatSession,
    ChatSessionJournalEntry,
    ChatSessionMessage,
    EditableDocument,
    LoreEntrySummary,
    MetadataSchema,
    PromptEntrySummary,
    SaveChatSessionRequest,
    StructureDocument,
  } from "./types";

  export let scene: EditableDocument | null = null;
  export let metadataSchema: MetadataSchema | null = null;
  export let promptEntries: PromptEntrySummary[] = [];
  export let assistantEntries: AssistantEntrySummary[] = [];
  export let loreEntries: LoreEntrySummary[] = [];
  export let structure: StructureDocument | null = null;
  export let defaultAssistantId: string = "";
  export let implicitContextMatcher: import("./implicitContextMatcher").CompiledMatcher | null = null;

  const dispatch = createEventDispatcher<{
    "body-change": void;
    focus: void;
    "open-chat": { entry: PromptEntrySummary; inputs: Record<string, unknown>; sceneId: string | null; assistantId: string };
  }>();

  const DEFAULT_CHAT_SYSTEM_PROMPT =
    "You are a brainstorming partner for a fiction writer. " +
    "Be concise, propose options, and don't write prose unless asked.";

  // Suppress unused-prop warnings for props Phase 4c+ wires in (preview
  // popover, inputs strip, future journal-scope rendering).
  $: void metadataSchema;
  $: void loreEntries;
  $: void structure;

  let chatSession: ChatSession | null = null;
  let loading = false;
  let loadError: string | null = null;
  let loadedChatId: string | null = null;

  // ---- chat working state (hydrated from chatSession on load) ----
  let chatHistory: ChatMessage[] = [];
  let chatRunning = false;
  let chatError: string | null = null;
  let chatLastMeta: { provider: string; model: string; latency_ms: number } | null = null;
  let chatInput = "";
  let chatScrollEl: HTMLDivElement | null = null;
  let chatSystemPrompt = DEFAULT_CHAT_SYSTEM_PROMPT;
  let chatPromptEntryId = "";
  let chatAssistantId = "";
  let activeChatTitle = "Untitled chat";
  let activeChatPinned = false;
  let activeChatJournal: ChatSessionJournalEntry[] = [];
  let activeChatJournalFreshIds = new Set<string>();
  let activeChatCacheWriteTimes: Record<string, string> = {};
  // V2 cost accounting — pluck the delta off the streaming `done` event
  // and forward it to the backend on the next persistActiveChat.
  let pendingTurnCost: number | null = null;
  let pendingTurnCacheWriteSlots: string[] = [];

  // ---- prompt-picker UI state (composer chip → dropdown) ----
  let promptPickerOpen = false;
  let promptPickerSearch = "";
  let promptPickerEl: HTMLDivElement | null = null;
  let promptPickerBtnEl: HTMLButtonElement | null = null;

  $: void maybeLoadChat(scene?.id ?? null);

  async function maybeLoadChat(chatId: string | null): Promise<void> {
    if (!chatId) {
      chatSession = null;
      loadError = null;
      loadedChatId = null;
      resetChatState();
      return;
    }
    if (chatId === loadedChatId) return;
    loading = true;
    loadError = null;
    try {
      const session = await api.readNode<ChatSession>(chatId);
      if (scene?.id !== chatId) return;
      chatSession = session;
      loadedChatId = chatId;
      applyChatSession(session);
    } catch (err) {
      if (scene?.id !== chatId) return;
      loadError = (err as Error).message || "Couldn't load chat.";
      chatSession = null;
      resetChatState();
    } finally {
      if (scene?.id === chatId) loading = false;
    }
  }

  function resetChatState() {
    chatHistory = [];
    chatRunning = false;
    chatError = null;
    chatLastMeta = null;
    chatInput = "";
    chatSystemPrompt = DEFAULT_CHAT_SYSTEM_PROMPT;
    chatPromptEntryId = "";
    chatAssistantId = "";
    activeChatTitle = "Untitled chat";
    activeChatPinned = false;
    activeChatJournal = [];
    activeChatJournalFreshIds = new Set();
    activeChatCacheWriteTimes = {};
    pendingTurnCost = null;
    pendingTurnCacheWriteSlots = [];
  }

  // Mirrors App.svelte's applyChatSession (the source of truth for the
  // hydration shape). Copy-not-shared so subsequent saves don't mutate
  // the fetched session object.
  function applyChatSession(session: ChatSession) {
    activeChatTitle = session.title || "Untitled chat";
    activeChatPinned = session.pinned;
    activeChatJournal = Array.isArray(session.journal) ? [...session.journal] : [];
    activeChatJournalFreshIds = new Set();
    activeChatCacheWriteTimes = { ...(session.cache_write_times ?? {}) };
    chatPromptEntryId = session.prompt_entry_id || "";
    chatAssistantId = session.assistant_id || "";
    chatSystemPrompt =
      session.system_prompt || (session.prompt_entry_id ? "" : DEFAULT_CHAT_SYSTEM_PROMPT);
    chatHistory = (session.messages || []).map((m: ChatSessionMessage) => ({
      role: m.role,
      content: m.content,
      truncated: !!m.truncated,
      thinking: m.thinking || undefined,
      journal_added: m.journal_added,
      usage: m.usage ?? null,
      cost_usd: m.cost_usd ?? null,
    }));
    chatLastMeta = null;
    chatError = null;
    chatInput = "";
    pendingTurnCost = null;
    pendingTurnCacheWriteSlots = [];
  }

  function promptTitle(promptId: string): string {
    if (!promptId) return "Freeform";
    const entry = promptEntries.find((p) => p.id === promptId);
    return entry?.title ?? "Unknown prompt";
  }

  function chatRoutedPromptEntries(): PromptEntrySummary[] {
    if (!metadataSchema) return [];
    return promptEntries.filter((entry) => {
      const def = metadataSchema?.entry_types[entry.entry_type];
      return def?.prompt?.context_strategy?.output?.kind === "chat_panel";
    });
  }

  function filteredChatPromptEntries(): PromptEntrySummary[] {
    const list = chatRoutedPromptEntries();
    const q = promptPickerSearch.trim().toLowerCase();
    const sorter = (a: PromptEntrySummary, b: PromptEntrySummary) =>
      a.title.localeCompare(b.title, undefined, { sensitivity: "base" });
    if (!q) return list.slice().sort(sorter);
    return list
      .filter((e) => e.title.toLowerCase().includes(q) || (e.entry_type || "").toLowerCase().includes(q))
      .sort(sorter);
  }

  function preferredAssistantForPrompt(entry: PromptEntrySummary): string {
    const raw = (entry.metadata ?? {})["preferred_assistant_id"];
    return typeof raw === "string" ? raw : "";
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

  async function pickPromptForChat(entry: PromptEntrySummary): Promise<void> {
    closeChatPromptPicker();
    if (isLocked) return;
    chatPromptEntryId = entry.id;
    const preferred = preferredAssistantForPrompt(entry);
    if (preferred) chatAssistantId = preferred;
    // First-send template render (rendering the prompt body into
    // system_prompt) lives in the next 4c slice. For now, leaving
    // chatSystemPrompt unset for prompt-bound chats matches the legacy
    // applyChatPromptPreset path — the brief disappears and the user
    // can still send a freeform turn against the bound prompt id.
    chatSystemPrompt = "";
    await persistActiveChat();
  }

  async function clearChatPrompt(): Promise<void> {
    if (isLocked) return;
    chatPromptEntryId = "";
    chatSystemPrompt = DEFAULT_CHAT_SYSTEM_PROMPT;
    await persistActiveChat();
  }

  async function handleAssistantChange(event: Event): Promise<void> {
    const target = event.target as HTMLSelectElement;
    chatAssistantId = target.value;
    await persistActiveChat();
  }

  async function handleBriefBlur(): Promise<void> {
    await persistActiveChat();
  }

  function handleDocumentClick(event: MouseEvent) {
    if (!promptPickerOpen) return;
    const target = event.target as Node;
    if (promptPickerEl?.contains(target)) return;
    if (promptPickerBtnEl?.contains(target)) return;
    closeChatPromptPicker();
  }

  function assistantTitle(assistantId: string): string {
    if (!assistantId) {
      const def = assistantEntries.find((a) => a.id === defaultAssistantId);
      return def ? `Default (${def.title})` : "Default";
    }
    return assistantEntries.find((a) => a.id === assistantId)?.title ?? "Unknown assistant";
  }

  $: isLocked = chatHistory.length > 0;

  // ---- send / stream / persist (ported from App.svelte) ----

  function deriveChatTitleFromHistory(): string | null {
    const firstUser = chatHistory.find((m) => m.role === "user");
    if (!firstUser) return null;
    const text = firstUser.content.trim().replace(/\s+/g, " ");
    if (!text) return null;
    return text.length > 50 ? text.slice(0, 50).trim() + "…" : text;
  }

  function currentChatSessionPayload(): SaveChatSessionRequest {
    let title = activeChatTitle || "Untitled chat";
    if (title === "Untitled chat") {
      const derived = deriveChatTitleFromHistory();
      if (derived) title = derived;
    }
    const cost_delta_usd = pendingTurnCost ?? undefined;
    const cache_write_slots =
      pendingTurnCacheWriteSlots.length > 0 ? [...pendingTurnCacheWriteSlots] : undefined;
    return {
      title,
      prompt_entry_id: chatPromptEntryId,
      assistant_id: chatAssistantId,
      system_prompt: chatSystemPrompt,
      pinned: activeChatPinned,
      context_items: [],
      messages: chatHistory.map((m) => ({
        role: m.role,
        content: m.content,
        thinking: m.thinking ?? "",
        truncated: !!m.truncated,
        usage: m.usage ?? null,
        cost_usd: m.cost_usd ?? null,
      })),
      inputs: {},
      cost_delta_usd,
      cache_write_slots,
    };
  }

  async function persistActiveChat(): Promise<void> {
    const chatId = scene?.id;
    if (!chatId) return;
    try {
      const saved = await api.saveNode<ChatSession>(chatId, currentChatSessionPayload());
      activeChatTitle = saved.title;
      activeChatPinned = saved.pinned;
      activeChatCacheWriteTimes = { ...(saved.cache_write_times ?? {}) };
      pendingTurnCost = null;
      pendingTurnCacheWriteSlots = [];
      // Refresh our local snapshot of the persisted session — keeps the
      // cost-total footer accurate without re-fetching.
      chatSession = saved;
      dispatch("body-change");
    } catch (e) {
      chatError = `Couldn't save chat: ${(e as Error).message}`;
    }
  }

  function appendToActiveChatJournal(added: ChatSessionJournalEntry[]): void {
    if (!added.length) return;
    const existingIds = new Set(activeChatJournal.map((e) => e.entry_id));
    const fresh = added.filter((e) => !existingIds.has(e.entry_id));
    if (!fresh.length) return;
    activeChatJournal = [...activeChatJournal, ...fresh];
    const freshIds = new Set(activeChatJournalFreshIds);
    for (const e of fresh) freshIds.add(e.entry_id);
    activeChatJournalFreshIds = freshIds;
    setTimeout(() => {
      const next = new Set(activeChatJournalFreshIds);
      for (const e of fresh) next.delete(e.entry_id);
      activeChatJournalFreshIds = next;
    }, 2500);
  }

  async function streamAssistantReply(onError: () => void): Promise<void> {
    chatHistory = [...chatHistory, { role: "assistant", content: "" }];
    const idx = chatHistory.length - 1;
    let scrollPending = false;
    const scheduleScroll = async () => {
      if (scrollPending) return;
      scrollPending = true;
      await tick();
      scrollPending = false;
      if (chatScrollEl) chatScrollEl.scrollTop = chatScrollEl.scrollHeight;
    };
    let errored = false;
    for await (const ev of api.aiChatStream({
      assistant_id: chatAssistantId || null,
      system_prompt: chatSystemPrompt,
      messages: chatHistory.slice(0, idx).map(({ role, content }) => ({ role, content })),
      chat_id: scene?.id ?? null,
    })) {
      if (ev.type === "delta") {
        chatHistory[idx].content += ev.text;
        chatHistory = chatHistory;
        scheduleScroll();
      } else if (ev.type === "thinking") {
        chatHistory[idx].thinking = (chatHistory[idx].thinking ?? "") + ev.text;
        chatHistory = chatHistory;
        scheduleScroll();
      } else if (ev.type === "done") {
        chatHistory[idx].truncated = ev.truncated;
        if (Array.isArray(ev.journal_added) && ev.journal_added.length > 0) {
          chatHistory[idx].journal_added = ev.journal_added;
          appendToActiveChatJournal(ev.journal_added);
        }
        if (ev.usage) chatHistory[idx].usage = ev.usage;
        if (typeof ev.cost_usd === "number") {
          chatHistory[idx].cost_usd = ev.cost_usd;
          pendingTurnCost = (pendingTurnCost ?? 0) + ev.cost_usd;
        }
        if (ev.usage && ev.usage.cache_write_tokens > 0) {
          if (!pendingTurnCacheWriteSlots.includes("system")) {
            pendingTurnCacheWriteSlots = [...pendingTurnCacheWriteSlots, "system"];
          }
        }
        chatHistory = chatHistory;
        chatLastMeta = { provider: ev.provider, model: ev.model, latency_ms: ev.latency_ms };
      } else if (ev.type === "error") {
        errored = true;
        chatError = ev.error || "Unknown error";
        chatHistory = chatHistory.slice(0, idx);
        onError();
      }
    }
    if (!errored && !chatHistory[idx]?.content && !chatHistory[idx]?.thinking) {
      chatHistory = chatHistory.slice(0, idx);
      chatError = "Model returned empty output.";
      onError();
    } else if (!errored) {
      void persistActiveChat();
    }
  }

  async function sendChat() {
    if (chatRunning) return;
    const text = chatInput.trim();
    if (!text) return;
    chatError = null;
    const userTurn: ChatMessage = { role: "user", content: text };
    chatHistory = [...chatHistory, userTurn];
    const userIdx = chatHistory.length - 1;
    chatInput = "";
    chatRunning = true;
    const rewindUser = () => {
      chatHistory = chatHistory.filter((_, i) => i !== userIdx);
      chatInput = text;
    };
    try {
      await streamAssistantReply(rewindUser);
    } catch (e) {
      chatError = (e as Error).message;
      rewindUser();
    } finally {
      chatRunning = false;
      await tick();
      if (chatScrollEl) chatScrollEl.scrollTop = chatScrollEl.scrollHeight;
    }
  }

  function clearChat() {
    chatHistory = [];
    chatLastMeta = null;
    chatError = null;
    // Reset cost-delta + cache-slot stamping so the next persist starts clean.
    pendingTurnCost = null;
    pendingTurnCacheWriteSlots = [];
    // Persist the clear so a reload doesn't resurrect the messages.
    void persistActiveChat();
  }

  function handleChatInputKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      sendChat();
    }
  }

  onMount(() => {
    document.addEventListener("mousedown", handleDocumentClick);
    return () => document.removeEventListener("mousedown", handleDocumentClick);
  });

  // ---------- Public methods (called via bind:this from parent) ----------
  export function getBodyMarkdown(): string {
    return "";
  }
</script>

<div class="chat-body-view" role="region" aria-label="Chat">
  {#if !scene}
    <p class="cbv-empty">No chat selected.</p>
  {:else if loading && !chatSession}
    <p class="cbv-empty">Loading chat…</p>
  {:else if loadError}
    <p class="cbv-error">Couldn't load chat: {loadError}</p>
  {:else if chatSession}
    <div class="cbv-composer-strip">
      <div class="cbv-prompt-anchor">
        <button
          type="button"
          class="cbv-chip cbv-chip-button"
          class:cbv-chip-locked={isLocked}
          class:cbv-chip-assigned={!!chatPromptEntryId}
          title={isLocked ? "Prompt is locked while this chat has messages." : "Pick a prompt"}
          bind:this={promptPickerBtnEl}
          on:click={() => void toggleChatPromptPicker()}
          disabled={isLocked && !chatPromptEntryId}
        >
          <span class="cbv-chip-glyph" aria-hidden="true">✨</span>
          <strong>{promptTitle(chatPromptEntryId)}</strong>
          {#if isLocked}
            <span class="cbv-chip-lock" aria-label="locked">🔒</span>
          {:else}
            <span class="cbv-chip-caret" aria-hidden="true">▾</span>
          {/if}
        </button>
        {#if chatPromptEntryId && !isLocked}
          <button
            type="button"
            class="cbv-chip-clear"
            title="Drop this prompt (revert to freeform chat)"
            on:click={() => void clearChatPrompt()}
          >×</button>
        {/if}
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
                on:click={() => void pickPromptForChat(entry)}
              >
                <strong>{entry.title}</strong>
                <small>{entry.entry_type}</small>
              </button>
            {:else}
              <p class="cbv-picker-empty">
                {promptPickerSearch
                  ? "No prompts match."
                  : "No chat-routed prompts. Create one with output_kind = chat_panel."}
              </p>
            {/each}
          </div>
        {/if}
      </div>
      <label class="cbv-assistant-anchor">
        <span class="cbv-chip-glyph" aria-hidden="true">🤖</span>
        <select
          class="cbv-assistant-select"
          class:cbv-chip-locked={isLocked}
          value={chatAssistantId}
          on:change={(e) => void handleAssistantChange(e)}
          disabled={isLocked}
          title={isLocked ? "Assistant is locked while this chat has messages." : "Pick an assistant"}
          aria-label="Assistant"
        >
          <option value="">Default ({assistantTitle("").replace(/^Default \(|\)$/g, "") || "machine default"})</option>
          {#each assistantEntries as assistant (assistant.id)}
            <option value={assistant.id}>{assistant.title}</option>
          {/each}
        </select>
      </label>
    </div>

    {#if !chatPromptEntryId}
      <label class="cbv-brief-label">
        <span>Brief</span>
        <textarea
          class="cbv-brief"
          bind:value={chatSystemPrompt}
          on:blur={() => void handleBriefBlur()}
          spellcheck="false"
        ></textarea>
      </label>
    {/if}

    <div class="cbv-messages" bind:this={chatScrollEl} aria-label="Chat history">
      {#if chatHistory.length === 0}
        <p class="cbv-empty">No messages yet. Ctrl/⌘+Enter to send.</p>
      {/if}
      {#each chatHistory as message, i (i)}
        <div class="cbv-message cbv-message-{message.role}">
          <header class="cbv-message-role">{message.role}</header>
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

    {#if chatLastMeta}
      <p class="cbv-meta">{chatLastMeta.provider} · {chatLastMeta.model} · {chatLastMeta.latency_ms} ms</p>
    {/if}
    {#if chatError}
      <p class="cbv-error">{chatError}</p>
    {/if}

    <PlainTextEditor
      class="cbv-input"
      value={chatInput}
      on:change={(e) => (chatInput = e.detail.value)}
      on:keydown={(e) => handleChatInputKeydown(e.detail)}
      on:focus={() => dispatch("focus")}
      placeholder="Message… (Ctrl/⌘+Enter to send)"
      ariaLabel="Chat message"
      minHeight={60}
      maxHeight={240}
      matcher={implicitContextMatcher}
    />

    <div class="cbv-action-row">
      <button type="button" disabled={!chatHistory.length || chatRunning} on:click={clearChat}>Clear</button>
      <button
        type="button"
        class="primary"
        disabled={chatRunning || !chatInput.trim()}
        on:click={() => void sendChat()}
      >
        {chatRunning ? "Sending…" : "Send"}
      </button>
    </div>

    {#if chatSession.cost_usd_total != null}
      <footer class="cbv-foot">
        Session cost: {formatCostEur(chatSession.cost_usd_total)}
      </footer>
    {/if}
  {/if}
</div>

<style>
  .chat-body-view {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    padding: 12px 16px 16px;
    gap: 10px;
    overflow: hidden;
  }

  .cbv-empty,
  .cbv-error,
  .cbv-meta {
    margin: 0;
    font-size: 13px;
    color: var(--color-text-muted, #5b6172);
  }
  .cbv-error {
    color: var(--color-text-error, #b3261e);
  }
  .cbv-meta {
    font-size: 11.5px;
  }

  .cbv-composer-strip {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .cbv-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 999px;
    background: var(--color-surface-muted, #f3f5fa);
    border: 1px solid var(--color-border, #d0d4dc);
    font-size: 13px;
  }
  .cbv-chip-assigned {
    background: color-mix(in srgb, var(--color-accent, #6366f1) 12%, transparent);
    border-color: var(--color-accent, #6366f1);
  }
  .cbv-chip-locked {
    opacity: 0.75;
  }
  .cbv-chip-glyph {
    font-size: 14px;
  }
  .cbv-chip-lock,
  .cbv-chip-caret {
    font-size: 12px;
  }
  .cbv-chip-button {
    cursor: pointer;
    font: inherit;
  }
  .cbv-chip-button[disabled] {
    cursor: not-allowed;
  }

  .cbv-prompt-anchor {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .cbv-chip-clear {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    border: 1px solid var(--color-border, #d0d4dc);
    background: var(--color-surface, #ffffff);
    cursor: pointer;
    font-size: 13px;
    line-height: 1;
    padding: 0;
  }

  .cbv-prompt-picker {
    position: absolute;
    top: 100%;
    left: 0;
    margin-top: 4px;
    z-index: 30;
    background: var(--color-surface, #ffffff);
    border: 1px solid var(--color-border, #d0d4dc);
    border-radius: 8px;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.08);
    padding: 6px;
    min-width: 240px;
    max-height: 320px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .cbv-picker-search {
    width: 100%;
    padding: 4px 6px;
    border-radius: 4px;
    border: 1px solid var(--color-border, #d0d4dc);
    font-size: 13px;
    margin-bottom: 4px;
  }
  .cbv-prompt-picker > button {
    text-align: left;
    padding: 6px 8px;
    border-radius: 4px;
    border: 1px solid transparent;
    background: transparent;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .cbv-prompt-picker > button:hover {
    background: var(--color-surface-muted, #f3f5fa);
  }
  .cbv-prompt-picker > button.cbv-picker-active {
    background: color-mix(in srgb, var(--color-accent, #6366f1) 12%, transparent);
    border-color: var(--color-accent, #6366f1);
  }
  .cbv-prompt-picker > button > small {
    font-size: 11px;
    color: var(--color-text-muted, #5b6172);
  }
  .cbv-picker-empty {
    margin: 4px 6px;
    font-size: 12px;
    color: var(--color-text-muted, #5b6172);
  }

  .cbv-assistant-anchor {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .cbv-assistant-select {
    padding: 4px 8px;
    border-radius: 999px;
    border: 1px solid var(--color-border, #d0d4dc);
    background: var(--color-surface-muted, #f3f5fa);
    font-size: 13px;
    font: inherit;
    cursor: pointer;
  }
  .cbv-assistant-select[disabled] {
    cursor: not-allowed;
  }

  .cbv-brief-label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 12px;
    color: var(--color-text-muted, #5b6172);
  }
  .cbv-brief {
    font-family: inherit;
    font-size: 13px;
    line-height: 1.4;
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid var(--color-border, #d0d4dc);
    background: var(--color-surface, #ffffff);
    color: var(--color-text, #1f2330);
    resize: vertical;
    min-height: 48px;
    max-height: 200px;
  }

  .cbv-messages {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding-right: 4px;
  }

  .cbv-message {
    border: 1px solid var(--color-border, #d0d4dc);
    border-radius: 8px;
    padding: 8px 10px;
    background: var(--color-surface, #ffffff);
  }
  .cbv-message-user {
    background: var(--color-surface-muted, #f3f5fa);
  }
  .cbv-message-role {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--color-text-muted, #5b6172);
    margin-bottom: 4px;
  }
  .cbv-message-content {
    font-size: 14px;
    line-height: 1.45;
    white-space: pre-wrap;
  }
  .cbv-typing {
    font-style: italic;
    color: var(--color-text-muted, #5b6172);
  }
  :global(.cbv-message-rendered) {
    font-size: 14px;
    line-height: 1.45;
  }
  :global(.cbv-message-rendered p) {
    margin: 0 0 0.6em;
  }
  :global(.cbv-message-rendered p:last-child) {
    margin-bottom: 0;
  }
  :global(.cbv-message-rendered pre) {
    margin: 0.4em 0;
    padding: 6px 8px;
    background: var(--color-surface-muted, #f3f5fa);
    border-radius: 6px;
    overflow-x: auto;
  }
  :global(.cbv-message-rendered code) {
    font-family: var(--font-mono, ui-monospace, "JetBrains Mono", monospace);
    font-size: 12.5px;
  }

  .cbv-thinking {
    margin-bottom: 6px;
    font-size: 12.5px;
    color: var(--color-text-muted, #5b6172);
  }
  .cbv-thinking summary {
    cursor: pointer;
  }

  .cbv-truncated {
    margin-top: 6px;
    font-size: 12px;
    color: var(--color-text-error, #b3261e);
  }

  .cbv-journal-added {
    margin-top: 6px;
    display: flex;
    flex-wrap: wrap;
    gap: 4px 6px;
    align-items: center;
    font-size: 12px;
  }
  .cbv-journal-label {
    color: var(--color-text-muted, #5b6172);
  }
  .cbv-journal-chip {
    padding: 1px 6px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--color-accent, #6366f1) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--color-accent, #6366f1) 35%, transparent);
  }

  .cbv-turn-meta {
    margin-top: 6px;
    font-size: 11.5px;
    color: var(--color-text-muted, #5b6172);
  }

  .cbv-action-row {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
  }
  .cbv-action-row button {
    padding: 4px 12px;
    font-size: 13px;
    border-radius: 6px;
    border: 1px solid var(--color-border, #d0d4dc);
    background: var(--color-surface, #ffffff);
    cursor: pointer;
  }
  .cbv-action-row button[disabled] {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .cbv-action-row button.primary {
    background: var(--color-accent, #6366f1);
    color: #fff;
    border-color: var(--color-accent, #6366f1);
  }

  .cbv-foot {
    margin: 0;
    font-size: 12px;
    color: var(--color-text-muted, #5b6172);
    border-top: 1px solid var(--color-border, #d0d4dc);
    padding-top: 6px;
  }
</style>
