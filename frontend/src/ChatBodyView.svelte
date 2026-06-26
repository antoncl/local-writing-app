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
  import PromptInputField from "./PromptInputField.svelte";
  import { renderChatContent } from "./chatMessageRender";
  import { formatCostEur, formatTokens } from "./money";
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
    PromptInputDefinition,
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
    // Fired after a title edit (from the pane header) persists, so the host
    // can refresh the Chats-pane roster + summaries.
    renamed: void;
    // Fired after a cost-accumulating turn persists, so the host can refresh
    // the project-wide cost rollup chip.
    "cost-changed": void;
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
  // Scene this chat was opened against (e.g. "invoke chat prompt" from a
  // prose scene). Passed as the target scene when rendering the template
  // at first-send so prompts that reference `scene` resolve it. "" for
  // freeform / Chats-pane chats.
  let chatTargetSceneId = "";
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

  // ---- 👁 preview popover state ----
  // The popover shows the rendered system_prompt — what the assistant
  // actually sees ahead of the conversation. For freeform chats that
  // IS the brief; for prompt-bound chats it's the post-render template.
  // Pure diagnostic — no fetch, just read-through of chatSystemPrompt.
  let chatPreviewPopoverOpen = false;
  let chatPreviewBtnEl: HTMLButtonElement | null = null;
  let chatPreviewPopoverEl: HTMLDivElement | null = null;

  // ---- declared-inputs state (filled before first send for prompt-bound chats) ----
  // Per-input draft values keyed by input.name. JSON-encoded for list-shaped
  // types so storage stays string-uniform. Hydrated from session.inputs;
  // persisted on every edit so a half-configured chat survives reload.
  let chatInputDrafts: Record<string, string> = {};
  // Collapse the strip after first send to reclaim space — user can re-expand.
  let chatInputsHidden = false;

  // ---- cost-estimate + TTL strip state ----
  // Per-slot TTL in seconds; mirrors App.svelte's SLOT_TTL_SECONDS.
  // Drives the TTL countdown chips. Slots not in this table get 5 min.
  const SLOT_TTL_SECONDS: Record<string, number> = {
    system: 3600,
    lore: 300,
  };
  // Tick counter — bumped every second by an onMount interval — so the
  // TTL chips' "remaining" recompute live. Anything else that wants a
  // 1Hz refresh can read this too.
  let ttlTick = 0;
  // Next-turn estimate. Recomputed whenever the inputs that drive it
  // change (prompt, assistant, drafts). Null when no prompt is bound —
  // a freeform brief renders no template so there's nothing to estimate
  // pre-send (the per-turn actuals on the assistant reply tell the user
  // what it cost retroactively).
  let chatEstimate: {
    tokens: number;
    cost_usd: number | null;
    caching_style: "none" | "auto" | "explicit" | null;
    cache_blocks: { label: string; tokens: number; cache_break_after: boolean }[];
  } | null = null;
  // Stale-response guard: every fetch grabs ourToken = ++chatEstimateToken;
  // on resolve we drop the response if the token moved. Out-of-order
  // resolutions are common when the user types fast.
  let chatEstimateToken = 0;

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
    chatTargetSceneId = "";
    activeChatTitle = "Untitled chat";
    activeChatPinned = false;
    activeChatJournal = [];
    activeChatJournalFreshIds = new Set();
    activeChatCacheWriteTimes = {};
    pendingTurnCost = null;
    pendingTurnCacheWriteSlots = [];
    chatInputDrafts = {};
    chatInputsHidden = false;
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
    chatTargetSceneId = session.target_scene_id || "";
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
    // Restore per-prompt input drafts. session.inputs is Record<string, unknown>;
    // PromptInputField stores list-shaped values JSON-encoded, so coerce
    // back to that representation on hydrate.
    chatInputDrafts = {};
    const raw = (session as unknown as { inputs?: Record<string, unknown> }).inputs ?? {};
    for (const [name, value] of Object.entries(raw)) {
      if (typeof value === "string") chatInputDrafts[name] = value;
      else chatInputDrafts[name] = JSON.stringify(value);
    }
    chatInputsHidden = false;
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
    // chatSystemPrompt stays empty until first-send; renderAndLockPromptTemplate
    // fills it in from api.aiPreview right before the first user turn ships
    // (deferred render lets the user edit input drafts freely).
    chatSystemPrompt = "";
    chatInputDrafts = seedInputDraftsFromEntry(entry);
    chatInputsHidden = false;
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

  function toggleChatPreviewPopover() {
    chatPreviewPopoverOpen = !chatPreviewPopoverOpen;
  }

  function handleDocumentClick(event: MouseEvent) {
    const target = event.target as Node;
    if (promptPickerOpen) {
      const insidePicker =
        promptPickerEl?.contains(target) || promptPickerBtnEl?.contains(target);
      if (!insidePicker) closeChatPromptPicker();
    }
    if (chatPreviewPopoverOpen) {
      const insidePreview =
        chatPreviewPopoverEl?.contains(target) || chatPreviewBtnEl?.contains(target);
      if (!insidePreview) chatPreviewPopoverOpen = false;
    }
  }

  function assistantTitle(assistantId: string): string {
    if (!assistantId) {
      const def = assistantEntries.find((a) => a.id === defaultAssistantId);
      return def ? `Default (${def.title})` : "Default";
    }
    return assistantEntries.find((a) => a.id === assistantId)?.title ?? "Unknown assistant";
  }

  $: isLocked = chatHistory.length > 0;

  // The prompt entry currently bound to the chat, if any. Used to drive
  // declaredInputs + the first-send template render.
  $: activePromptEntry = chatPromptEntryId
    ? promptEntries.find((p) => p.id === chatPromptEntryId) ?? null
    : null;
  $: declaredInputs = activePromptEntry?.inputs ?? [];

  function defaultDraftFor(input: PromptInputDefinition): string {
    if (input.default !== undefined && input.default !== null) return String(input.default);
    return input.type === "boolean" ? "false" : "";
  }

  function seedInputDraftsFromEntry(entry: PromptEntrySummary): Record<string, string> {
    const drafts: Record<string, string> = {};
    for (const input of entry.inputs ?? []) drafts[input.name] = defaultDraftFor(input);
    return drafts;
  }

  function isInputMissing(input: PromptInputDefinition, raw: string | undefined): boolean {
    if (input.type === "entity_ref_list" || input.type === "context_pick") {
      try {
        const parsed = JSON.parse(raw || "[]");
        return !Array.isArray(parsed) || parsed.length === 0;
      } catch {
        return true;
      }
    }
    return !raw?.trim();
  }
  $: missingRequiredInputs = declaredInputs.filter(
    (i) => i.required && isInputMissing(i, chatInputDrafts[i.name]),
  );

  function coerceChatInputValue(raw: string, type: PromptInputDefinition["type"]): unknown {
    const trimmed = raw.trim();
    if (type === "number") {
      if (trimmed === "") return null;
      const parsed = Number(trimmed);
      return Number.isFinite(parsed) ? parsed : trimmed;
    }
    if (type === "boolean") return trimmed.toLowerCase() === "true";
    if (type === "entity_ref_list" || type === "context_pick") {
      if (!trimmed) return type === "context_pick" ? [] : null;
      try {
        const parsed = JSON.parse(trimmed);
        return Array.isArray(parsed) ? parsed : (type === "context_pick" ? [] : null);
      } catch {
        return type === "context_pick" ? [] : null;
      }
    }
    return trimmed;
  }

  async function updateChatInputDraft(name: string, value: string): Promise<void> {
    chatInputDrafts = { ...chatInputDrafts, [name]: value };
    await persistActiveChat();
  }

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
      target_scene_id: chatTargetSceneId,
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
      const hadCost = pendingTurnCost != null;
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
      // A turn that accumulated cost moves the project-wide rollup chip.
      // App owns that chip, so signal it to re-fetch (mirrors the old
      // bespoke persistActiveChat's refreshProjectCost call).
      if (hadCost) dispatch("cost-changed");
    } catch (e) {
      chatError = `Couldn't save chat: ${(e as Error).message}`;
    }
  }

  // Title rename feed from the pane header (NodeEditor owns the input;
  // ChatBodyView owns the title state so per-turn saves never revert it).
  // Debounced so typing doesn't hammer the backend; `renamed` lets the host
  // refresh the Chats roster once the new title lands.
  let titleSaveTimer: ReturnType<typeof setTimeout> | null = null;
  export function setTitleFromPane(next: string): void {
    if (!loadedChatId) return;
    if (next === activeChatTitle) return;
    activeChatTitle = next;
    if (titleSaveTimer) clearTimeout(titleSaveTimer);
    titleSaveTimer = setTimeout(() => {
      titleSaveTimer = null;
      void persistActiveChat().then(() => dispatch("renamed"));
    }, 500);
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
    if (missingRequiredInputs.length > 0) {
      chatError = `Missing required: ${missingRequiredInputs.map((i) => i.label || i.name).join(", ")}.`;
      return;
    }
    const text = chatInput.trim();
    // Empty composer text is allowed only when the chat is bound to a
    // prompt AND has no history yet — i.e. the template IS the message.
    // Mirrors sendChat in App.svelte (McKee-style self-contained prompts
    // shouldn't force the user to type "Do it").
    const isFirstTurnFromPrompt = !!activePromptEntry && chatHistory.length === 0;
    if (!text && !isFirstTurnFromPrompt) return;
    const isFirstSubmission = chatHistory.length === 0;
    chatError = null;
    // First-send template render: defer to renderAndLockPromptTemplate
    // when the chat is bound to a prompt that hasn't been rendered yet
    // AND that prompt has declared inputs (the indication that the
    // template needs values plugged in). Gating matches App.svelte's
    // bespoke sendChat.
    if (activePromptEntry && !chatSystemPrompt && (activePromptEntry.inputs ?? []).length > 0) {
      chatRunning = true;
      try {
        const ok = await renderAndLockPromptTemplate(activePromptEntry);
        if (!ok) {
          chatRunning = false;
          return;
        }
        await persistActiveChat();
      } finally {
        chatRunning = false;
      }
    }
    let userIdx = -1;
    if (text) {
      const userTurn: ChatMessage = { role: "user", content: text };
      chatHistory = [...chatHistory, userTurn];
      userIdx = chatHistory.length - 1;
    }
    chatInput = "";
    chatRunning = true;
    const rewindUser = () => {
      if (userIdx >= 0) chatHistory = chatHistory.filter((_, i) => i !== userIdx);
      chatInput = text;
    };
    try {
      await streamAssistantReply(rewindUser);
      if (isFirstSubmission) chatInputsHidden = true;
    } catch (e) {
      chatError = (e as Error).message;
      rewindUser();
    } finally {
      chatRunning = false;
      await tick();
      if (chatScrollEl) chatScrollEl.scrollTop = chatScrollEl.scrollHeight;
    }
  }

  // First-send template render. Mirrors App.svelte's
  // renderAndLockPromptTemplate (the source of truth). Called from
  // sendChat right before the first user turn ships, when the chat is
  // bound to a prompt that hasn't been rendered yet. After this the
  // preset is locked (chatSystemPrompt is non-empty, chatHistory may
  // hold initial turns); subsequent sends skip this path.
  async function renderAndLockPromptTemplate(entry: PromptEntrySummary): Promise<boolean> {
    const inputs: Record<string, unknown> = {};
    for (const input of entry.inputs ?? []) {
      const raw = chatInputDrafts[input.name] ?? "";
      const coerced = coerceChatInputValue(raw, input.type);
      if (coerced !== null && coerced !== "") inputs[input.name] = coerced;
    }
    try {
      const preview = await api.aiPreview({
        template_source: entry.body_markdown,
        target_scene_id: chatTargetSceneId,
        inputs,
        commit: false,
      });
      const messages = preview.messages ?? [];
      const flatten = (blocks: { text: string }[]) => blocks.map((b) => b.text).join("");
      const systemBlocks = messages
        .filter((m) => m.role === "system")
        .map((m) => flatten(m.blocks));
      const initialTurns = messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role as "user" | "assistant", content: flatten(m.blocks) }));
      chatSystemPrompt = systemBlocks.join("\n\n");
      if (initialTurns.length > 0) chatHistory = [...initialTurns];
      return true;
    } catch (e) {
      chatError = `Couldn't render prompt template: ${(e as Error).message}`;
      return false;
    }
  }

  function clearChat() {
    chatHistory = [];
    chatLastMeta = null;
    chatError = null;
    chatInputsHidden = false;
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
    const ttlInterval = setInterval(() => { ttlTick += 1; }, 1000);
    return () => {
      document.removeEventListener("mousedown", handleDocumentClick);
      clearInterval(ttlInterval);
    };
  });

  async function fetchChatEstimate(): Promise<void> {
    if (!chatPromptEntryId) {
      chatEstimate = null;
      return;
    }
    const entry = promptEntries.find((p) => p.id === chatPromptEntryId);
    if (!entry) {
      chatEstimate = null;
      return;
    }
    const ourToken = ++chatEstimateToken;
    const inputs: Record<string, unknown> = {};
    for (const declared of entry.inputs ?? []) {
      const raw = chatInputDrafts[declared.name] ?? "";
      const coerced = coerceChatInputValue(raw, declared.type);
      if (coerced !== null && coerced !== "") inputs[declared.name] = coerced;
    }
    try {
      const preview = await api.aiPreview({
        template_source: entry.body_markdown,
        target_scene_id: chatTargetSceneId,
        inputs,
        commit: false,
        assistant_id: chatAssistantId || null,
      });
      if (ourToken !== chatEstimateToken) return;
      chatEstimate = {
        tokens: preview.estimated_tokens ?? 0,
        cost_usd: preview.estimated_cost_usd ?? null,
        caching_style: preview.caching_style ?? null,
        cache_blocks: (preview.cache_blocks ?? []).map((b) => ({
          label: b.label,
          tokens: b.tokens,
          cache_break_after: b.cache_break_after,
        })),
      };
    } catch {
      // Surface errors via the future preview popover, not the strip —
      // keep the estimate quiet rather than blinking "—".
    }
  }

  // Per-slot TTL chips. Reads ttlTick so chips recompute live, reads
  // activeChatCacheWriteTimes so they refresh when a new turn stamps a
  // slot.
  function ttlChipsFor(times: Record<string, string>, _tick: number) {
    if (!times || Object.keys(times).length === 0) return [];
    const now = Date.now();
    return Object.entries(times).map(([slot, iso]) => {
      const writtenAt = Date.parse(iso);
      const ttl = (SLOT_TTL_SECONDS[slot] ?? 300) * 1000;
      const remainingMs = writtenAt + ttl - now;
      const remainingSec = Math.max(0, Math.round(remainingMs / 1000));
      const label = slot.charAt(0).toUpperCase() + slot.slice(1);
      const ttlLabel = ttl >= 3600_000 ? "1h" : "5m";
      let formatted: string;
      if (remainingSec <= 0) formatted = "expired";
      else if (remainingSec >= 60) formatted = `${Math.floor(remainingSec / 60)}m`;
      else formatted = `${remainingSec}s`;
      return { slot, label, ttlLabel, formatted, expired: remainingSec <= 0 };
    });
  }
  $: ttlChips = ttlChipsFor(activeChatCacheWriteTimes, ttlTick);

  // Re-fetch estimate when any input that drives it changes. Each dep
  // read on its own line so Svelte tracks them (see
  // [[feedback-svelte5-reactivity-traps]]).
  $: {
    chatPromptEntryId;
    chatAssistantId;
    chatInputDrafts;
    promptEntries.length;
    void fetchChatEstimate();
  }

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
      <div class="cbv-preview-anchor">
        <button
          type="button"
          class="cbv-preview-icon"
          class:cbv-preview-icon-active={chatPreviewPopoverOpen}
          bind:this={chatPreviewBtnEl}
          title="Preview what's sent — system message + attached context"
          aria-label="Preview what's sent"
          aria-expanded={chatPreviewPopoverOpen}
          on:click={toggleChatPreviewPopover}
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
                on:click={() => (chatPreviewPopoverOpen = false)}
              >×</button>
            </header>
            <div class="cbv-preview-popover-body">
              {#if chatSystemPrompt && chatSystemPrompt.trim()}
                <pre class="cbv-preview-content">{chatSystemPrompt}</pre>
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

    {#if declaredInputs.length > 0}
      <div class="cbv-inputs-strip" class:cbv-inputs-locked={isLocked}>
        {#if isLocked}
          <button
            type="button"
            class="cbv-inputs-toggle"
            aria-expanded={!chatInputsHidden}
            on:click={() => (chatInputsHidden = !chatInputsHidden)}
          >{chatInputsHidden ? "▸ Show inputs" : "▾ Hide inputs"}</button>
        {/if}
        {#if !isLocked || !chatInputsHidden}
          <div class="cbv-inputs-fields">
            {#each declaredInputs as input (input.name)}
              {@const missing = input.required && isInputMissing(input, chatInputDrafts[input.name])}
              <label class="cbv-input-field" class:cbv-input-missing={missing} class:cbv-input-disabled={isLocked}>
                <span class="cbv-input-label">
                  {input.label || input.name}{#if input.required}<span class="cbv-required-marker" title="Required"> *</span>{/if}
                </span>
                <PromptInputField
                  input={input}
                  value={chatInputDrafts[input.name] ?? ""}
                  metadataSchema={metadataSchema}
                  excludeId={null}
                  ariaLabel={input.label || input.name}
                  structure={structure}
                  loreEntries={loreEntries}
                  promptEntries={promptEntries}
                  implicitContextMatcher={implicitContextMatcher}
                  on:change={(event) => !isLocked && void updateChatInputDraft(input.name, event.detail.value)}
                />
              </label>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    {#if activeChatJournal.length > 0}
      <div class="cbv-journal-scope" aria-label="Lore entries currently in this chat's implicit-context cache">
        <span class="cbv-journal-scope-label">In context:</span>
        {#each activeChatJournal as entry (entry.entry_id)}
          <span
            class="cbv-journal-scope-chip"
            class:cbv-journal-scope-chip-fresh={activeChatJournalFreshIds.has(entry.entry_id)}
            class:cbv-journal-scope-chip-depth1={entry.source === "depth1_expansion"}
            title={entry.source === "depth1_expansion"
              ? `${entry.title} — pulled in because another entity's body mentions it`
              : `${entry.title} — detected in a user message`}
          >{entry.title || entry.entry_id}</span>
        {/each}
      </div>
    {/if}

    {#if chatEstimate}
      <div class="cbv-estimate-strip" title="Estimated input cost for the bound prompt. Output cost depends on the response.">
        <span class="cbv-estimate-tokens">{formatTokens(chatEstimate.tokens)} tok</span>
        <span class="cbv-estimate-sep">·</span>
        <span class="cbv-estimate-cost">{formatCostEur(chatEstimate.cost_usd)}</span>
        {#if chatEstimate.caching_style === "explicit" && chatEstimate.cache_blocks.length > 1}
          <span class="cbv-estimate-sep">·</span>
          {#each chatEstimate.cache_blocks as block, i}
            <span class="cbv-estimate-chip">{block.label} {formatTokens(block.tokens)}</span>
            {#if i < chatEstimate.cache_blocks.length - 1}<span class="cbv-estimate-sep">·</span>{/if}
          {/each}
        {/if}
      </div>
    {/if}
    {#if ttlChips.length > 0 && chatEstimate?.caching_style === "explicit"}
      <div class="cbv-ttl-strip" title="Cache lifetime estimates. Provider may evict early under load — these are not authoritative.">
        {#each ttlChips as chip, i}
          <span class="cbv-ttl-chip" class:cbv-ttl-expired={chip.expired}>
            {chip.label} ({chip.ttlLabel}) {chip.formatted}
          </span>
          {#if i < ttlChips.length - 1}<span class="cbv-estimate-sep">·</span>{/if}
        {/each}
      </div>
    {/if}

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
        disabled={chatRunning
          || missingRequiredInputs.length > 0
          || (!chatInput.trim() && !(activePromptEntry && chatHistory.length === 0))}
        title={missingRequiredInputs.length > 0
          ? `Fill required input${missingRequiredInputs.length > 1 ? "s" : ""}: ${missingRequiredInputs.map((i) => i.label || i.name).join(", ")}`
          : (!chatInput.trim() && activePromptEntry && chatHistory.length === 0)
            ? "Send the prompt as-is (no extra message)"
            : ""}
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

  .cbv-preview-anchor {
    position: relative;
    display: inline-flex;
    align-items: center;
  }
  .cbv-preview-icon {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    border: 1px solid var(--color-border, #d0d4dc);
    background: var(--color-surface, #ffffff);
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
    padding: 0;
  }
  .cbv-preview-icon-active {
    background: color-mix(in srgb, var(--color-accent, #6366f1) 12%, transparent);
    border-color: var(--color-accent, #6366f1);
  }
  .cbv-preview-popover {
    position: absolute;
    top: 100%;
    right: 0;
    margin-top: 6px;
    z-index: 40;
    width: 360px;
    max-height: 60vh;
    background: var(--color-surface, #ffffff);
    border: 1px solid var(--color-border, #d0d4dc);
    border-radius: 8px;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.10);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .cbv-preview-popover-header {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 6px 8px;
    border-bottom: 1px solid var(--color-border, #d0d4dc);
    background: var(--color-surface-muted, #f3f5fa);
    font-size: 12px;
  }
  .cbv-preview-popover-header strong {
    font-size: 13px;
  }
  .cbv-preview-popover-header small {
    color: var(--color-text-muted, #5b6172);
    flex: 1;
  }
  .cbv-preview-popover-close {
    background: transparent;
    border: none;
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
    padding: 0 4px;
    color: var(--color-text-muted, #5b6172);
  }
  .cbv-preview-popover-body {
    padding: 8px;
    overflow-y: auto;
    flex: 1;
  }
  .cbv-preview-content {
    margin: 0 0 8px;
    font-family: var(--font-mono, ui-monospace, "JetBrains Mono", monospace);
    font-size: 12px;
    line-height: 1.4;
    white-space: pre-wrap;
    word-wrap: break-word;
  }
  .cbv-preview-hint {
    font-style: italic;
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

  .cbv-inputs-strip {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid var(--color-border, #d0d4dc);
    background: var(--color-surface-muted, #f3f5fa);
  }
  .cbv-inputs-toggle {
    align-self: flex-start;
    padding: 2px 6px;
    font-size: 12px;
    background: transparent;
    border: none;
    cursor: pointer;
    color: var(--color-text-muted, #5b6172);
  }
  .cbv-inputs-fields {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .cbv-input-field {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 12px;
  }
  .cbv-input-label {
    color: var(--color-text-muted, #5b6172);
  }
  .cbv-required-marker {
    color: var(--color-text-error, #b3261e);
  }
  .cbv-input-field.cbv-input-missing > .cbv-input-label {
    color: var(--color-text-error, #b3261e);
  }
  .cbv-input-field.cbv-input-disabled {
    opacity: 0.65;
  }

  .cbv-journal-scope {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 6px;
    align-items: center;
    font-size: 12px;
  }
  .cbv-journal-scope-label {
    color: var(--color-text-muted, #5b6172);
  }
  .cbv-journal-scope-chip {
    padding: 1px 6px;
    border-radius: 999px;
    background: var(--color-surface-muted, #f3f5fa);
    border: 1px solid var(--color-border, #d0d4dc);
    transition: background 250ms ease-out, border-color 250ms ease-out;
  }
  .cbv-journal-scope-chip-depth1 {
    border-style: dashed;
  }
  .cbv-journal-scope-chip-fresh {
    background: color-mix(in srgb, var(--color-accent, #6366f1) 22%, transparent);
    border-color: var(--color-accent, #6366f1);
  }

  .cbv-estimate-strip,
  .cbv-ttl-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 4px;
    font-size: 11.5px;
    color: var(--color-text-muted, #5b6172);
  }
  .cbv-estimate-sep {
    color: var(--color-border, #d0d4dc);
  }
  .cbv-estimate-chip {
    padding: 0 5px;
    border-radius: 4px;
    background: var(--color-surface-muted, #f3f5fa);
    border: 1px solid var(--color-border, #d0d4dc);
  }
  .cbv-ttl-chip {
    padding: 0 5px;
    border-radius: 4px;
    background: var(--color-surface-muted, #f3f5fa);
    border: 1px solid var(--color-border, #d0d4dc);
  }
  .cbv-ttl-chip.cbv-ttl-expired {
    color: var(--color-text-error, #b3261e);
    border-color: var(--color-text-error, #b3261e);
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
