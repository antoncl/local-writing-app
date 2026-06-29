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
    PromptEntrySummary,
    PromptInputDefinition,
    SaveChatSessionRequest,
    StructureDocument,
  } from "./types";
  import { metadataSchemaStore } from "./stores/schema";

  export let scene: EditableDocument | null = null;
  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  $: metadataSchema = $metadataSchemaStore;
  export let promptEntries: PromptEntrySummary[] = [];
  export let assistantEntries: AssistantEntrySummary[] = [];
  export let loreEntries: LoreEntrySummary[] = [];
  export let structure: StructureDocument | null = null;
  // Research tree (sibling to manuscript) — threaded to the picker.
  export let researchStructure: StructureDocument | null = null;
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

  // Suppress unused-prop warnings for props Phase 4c+ wires in (preview
  // popover, inputs strip, future journal-scope rendering).
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
  // Holds the rendered template for a prompt-bound chat (filled by
  // renderAndLockPromptTemplate on first send) or — for legacy sessions
  // — the freeform system message that was authored before chats had
  // to be prompt-bound. Empty for fresh chats; never user-editable now.
  let chatSystemPrompt = "";
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

  // ---- assistant-picker UI state (mirrors prompt picker; replaces native <select>) ----
  let assistantPickerOpen = false;
  let assistantPickerSearch = "";
  let assistantPickerEl: HTMLDivElement | null = null;
  let assistantPickerBtnEl: HTMLButtonElement | null = null;

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
    chatSystemPrompt = "";
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
    chatSystemPrompt = session.system_prompt || "";
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
    // Collapse the inputs strip by default once the chat is locked (has
    // turns) — the conversation owns the height; the user can re-expand to
    // inspect what was sent. Open it for fresh/unlocked chats still being set up.
    chatInputsHidden = (session.messages || []).length > 0;
  }

  function promptTitle(promptId: string): string {
    if (!promptId) return "Pick a prompt";
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

  function filteredAssistantEntries(): AssistantEntrySummary[] {
    const q = assistantPickerSearch.trim().toLowerCase();
    const sorter = (a: AssistantEntrySummary, b: AssistantEntrySummary) =>
      a.title.localeCompare(b.title, undefined, { sensitivity: "base" });
    if (!q) return assistantEntries.slice().sort(sorter);
    return assistantEntries
      .filter((e) => e.title.toLowerCase().includes(q) || (e.entry_type || "").toLowerCase().includes(q))
      .sort(sorter);
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

  async function pickAssistantForChat(id: string): Promise<void> {
    closeAssistantPicker();
    if (isLocked) return;
    chatAssistantId = id;
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
    if (assistantPickerOpen) {
      const insidePicker =
        assistantPickerEl?.contains(target) || assistantPickerBtnEl?.contains(target);
      if (!insidePicker) closeAssistantPicker();
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
        template_source: entry.body,
        target_scene_id: chatTargetSceneId,
        inputs,
        commit: false,
      });
      // Render errors come back as 200 + preview.error from /api/ai/preview
      // (exploratory endpoint). At first-send we DO want to surface them —
      // the user is committing to a model call that won't have a valid prompt.
      if (preview.error) {
        chatError = `Couldn't render prompt template: ${preview.error.message}`;
        return false;
      }
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
        template_source: entry.body,
        target_scene_id: chatTargetSceneId,
        inputs,
        commit: false,
        assistant_id: chatAssistantId || null,
      });
      if (ourToken !== chatEstimateToken) return;
      // Preview render errors come back as 200 + preview.error. Don't show
      // them in the estimate strip — they'll surface when the user sends.
      if (preview.error) {
        chatEstimate = null;
        return;
      }
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
      // Non-render failure — same UX.
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
  export function getBody(): string {
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
      <div class="cbv-prompt-anchor">
        <button
          type="button"
          class="cbv-chip cbv-chip-button cbv-chip-graphite"
          class:cbv-chip-locked={isLocked}
          title={isLocked ? "Assistant is locked while this chat has messages." : "Pick an assistant"}
          bind:this={assistantPickerBtnEl}
          on:click={() => void toggleAssistantPicker()}
          disabled={isLocked}
          aria-label="Assistant"
        >
          <span class="cbv-chip-glyph" aria-hidden="true">🤖</span>
          <strong>{assistantTitle(chatAssistantId)}</strong>
          {#if isLocked}
            <span class="cbv-chip-lock" aria-label="locked">🔒</span>
          {:else}
            <span class="cbv-chip-caret" aria-hidden="true">▾</span>
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
              on:click={() => void pickAssistantForChat("")}
            >
              <strong>Default</strong>
              <small>{assistantTitle("").replace(/^Default \(|\)$/g, "") || "machine default"}</small>
            </button>
            {#each filteredAssistantEntries() as assistant (assistant.id)}
              <button
                type="button"
                class:cbv-picker-active={assistant.id === chatAssistantId}
                on:click={() => void pickAssistantForChat(assistant.id)}
              >
                <strong>{assistant.title}</strong>
                <small>{assistant.entry_type}</small>
              </button>
            {:else}
              <p class="cbv-picker-empty">
                {assistantPickerSearch ? "No assistants match." : "No assistants configured."}
              </p>
            {/each}
          </div>
        {/if}
      </div>
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

    <div class="cbv-messages" bind:this={chatScrollEl} aria-label="Chat history">
      {#if chatHistory.length === 0}
        <p class="cbv-empty">No messages yet. Ctrl/⌘+Enter to send.</p>
      {/if}
      {#each chatHistory as message, i (i)}
        <div class="cbv-message cbv-message-{message.role}">
          <header class="cbv-message-role">
            {#if message.role === "assistant"}Claude<span class="cbv-role-dot" aria-hidden="true"></span>{:else}You{/if}
          </header>
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
                  excludeId={null}
                  ariaLabel={input.label || input.name}
                  structure={structure}
                  researchStructure={researchStructure}
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
          >
            {entry.title || entry.entry_id}
            {#if activeChatJournalFreshIds.has(entry.entry_id)}
              <span class="cbv-journal-scope-pip cbv-journal-scope-pip-fresh">FRESH</span>
            {:else if entry.source === "depth1_expansion"}
              <span class="cbv-journal-scope-pip cbv-journal-scope-pip-depth1">↳ depth 1</span>
            {/if}
          </span>
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
    padding: 12px 14px 14px 17px;
    gap: 10px;
    overflow: hidden;
    /* The body owns one stripe in its kind (chat = graphite) color. */
    box-shadow: inset 3px 0 0 0 var(--k-graphite);
    background: var(--surface);
  }

  .cbv-empty,
  .cbv-error,
  .cbv-meta {
    margin: 0;
    font-size: 13px;
    color: var(--text-3);
  }
  .cbv-error { color: var(--danger); }
  .cbv-meta { font-size: 11.5px; }

  /* ---- 1 · composer strip ---- */
  .cbv-composer-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    padding-bottom: 11px;
    border-bottom: 1px solid var(--divider);
  }
  .cbv-chip {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 5px 11px;
    border-radius: 999px;
    background: var(--surface);
    border: 1px solid var(--border);
    font-size: 12px;
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
  .cbv-chip-glyph { font-size: 13px; }
  .cbv-chip-lock { font-size: 11px; opacity: 0.65; }
  .cbv-chip-caret { font-size: 11px; opacity: 0.7; }
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
    border: 1px solid var(--border); font-size: 13px; margin-bottom: 4px;
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
  .cbv-prompt-picker > button > strong { font-weight: 600; font-size: 13px; }
  .cbv-prompt-picker > button > small { font-size: 11px; color: var(--text-3); }
  .cbv-picker-empty { margin: 4px 6px; font-size: 12px; color: var(--text-3); }

  /* Assistant chip = graphite variant of .cbv-chip. Trigger + popover
     mirror the prompt picker exactly so both reads at the same height
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
    cursor: pointer; font-size: 15px; line-height: 1; padding: 0; color: var(--text-2);
  }
  .cbv-preview-icon:hover { background: var(--inset); }
  .cbv-preview-icon-active { background: var(--accent-soft); border-color: var(--accent-soft2); }

  /* 3 · preview popover. */
  .cbv-preview-popover {
    position: absolute; top: 100%; right: 0; margin-top: 6px; z-index: 40;
    width: 380px; max-height: 60vh; background: var(--surface);
    border: 1px solid var(--border-strong); border-radius: 12px;
    box-shadow: 0 12px 30px var(--shadow2); display: flex; flex-direction: column; overflow: hidden;
  }
  .cbv-preview-popover-header {
    display: flex; align-items: baseline; gap: 8px; padding: 9px 13px;
    border-bottom: 1px solid var(--divider); background: var(--panel); font-size: 12px;
  }
  .cbv-preview-popover-header strong { font-size: 12px; font-weight: 600; color: var(--text); }
  .cbv-preview-popover-header small { color: var(--text-3); flex: 1; font-size: 10.5px; }
  .cbv-preview-popover-close {
    background: transparent; border: none; cursor: pointer; font-size: 15px;
    line-height: 1; padding: 0 2px; color: var(--text-3);
  }
  .cbv-preview-popover-body { padding: 12px 14px; overflow-y: auto; flex: 1; }
  .cbv-preview-content {
    margin: 0 0 8px; font-family: ui-monospace, "JetBrains Mono", monospace;
    font-size: 12px; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; color: var(--text);
  }
  .cbv-preview-hint { font-style: italic; }

  /* ---- 4 · messages ---- */
  .cbv-messages {
    flex: 1 1 0; min-height: 96px; overflow-y: auto;
    display: flex; flex-direction: column; gap: 16px; padding: 16px 14px;
  }
  /* The composer + strips + input + action row keep their natural height;
     only the messages region flexes (and scrolls). Prevents the message
     input collapsing when the conversation is tall. */
  .cbv-composer-strip,
  .cbv-inputs-strip,
  .cbv-journal-scope,
  .cbv-estimate-strip,
  .cbv-ttl-strip,
  .cbv-action-row,
  .cbv-foot,
  :global(.chat-body-view > .cbv-input) {
    flex: 0 0 auto;
  }
  .cbv-message { display: flex; flex-direction: column; gap: 6px; max-width: 100%; }
  .cbv-message-user { align-items: flex-end; }
  .cbv-message-assistant { align-items: flex-start; }
  .cbv-message-role {
    display: flex; align-items: center; gap: 6px; font-size: 10px; font-weight: 800;
    letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-3); padding: 0 2px;
  }
  .cbv-role-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--k-graphite); }
  .cbv-message-content {
    font-size: 13.5px; line-height: 1.6; white-space: pre-wrap; padding: 10px 13px;
  }
  .cbv-message-user .cbv-message-content {
    max-width: 78%; border-radius: 13px 13px 4px 13px;
    background: var(--accent-soft); border: 1px solid var(--accent-soft2); color: var(--text);
  }
  .cbv-message-assistant .cbv-message-content {
    max-width: 82%; border-radius: 13px 13px 13px 4px; white-space: normal;
    background: var(--surface); border: 1px solid var(--border); box-shadow: 0 1px 3px var(--shadow); color: var(--text);
    padding: 11px 14px;
  }
  .cbv-typing { font-style: italic; color: var(--text-3); }
  :global(.cbv-message-rendered) { font-size: 13.5px; line-height: 1.6; }
  :global(.cbv-message-rendered p) { margin: 0 0 0.6em; }
  :global(.cbv-message-rendered p:last-child) { margin-bottom: 0; }
  :global(.cbv-message-rendered pre) {
    margin: 0.4em 0; padding: 8px 10px; background: var(--inset); border-radius: 8px; overflow-x: auto;
  }
  :global(.cbv-message-rendered code) { font-family: ui-monospace, "JetBrains Mono", monospace; font-size: 12.5px; }

  /* 4a · thinking accordion. */
  .cbv-thinking {
    max-width: 82%; font-size: 11.5px; color: var(--text-3);
    border: 1px solid var(--divider); border-radius: 9px; background: var(--inset); padding: 5px 11px;
  }
  .cbv-thinking summary { cursor: pointer; list-style: none; }
  .cbv-thinking summary::-webkit-details-marker { display: none; }
  .cbv-thinking summary::before { content: "▸  "; color: var(--text-3); }
  .cbv-thinking[open] summary::before { content: "▾  "; }

  /* 4d · truncation banner. */
  .cbv-truncated {
    display: inline-flex; align-items: center; gap: 7px; padding: 7px 12px;
    border: 1px solid var(--star-border); border-radius: 9px; background: var(--star-soft);
    font-size: 11.5px; color: var(--star);
  }
  .cbv-truncated::before { content: "⚠"; }

  /* 4b · journal-added chip. */
  .cbv-journal-added {
    display: inline-flex; flex-wrap: wrap; gap: 5px 6px; align-items: center; font-size: 11px;
  }
  .cbv-journal-label {
    font-size: 9.5px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-3);
  }
  .cbv-journal-chip {
    display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border-radius: 999px;
    background: var(--accent-soft); border: 1px solid var(--accent-soft2);
    color: var(--accent-strong); font-weight: 600;
  }
  .cbv-journal-chip::before { content: "✚"; font-size: 9px; }

  /* 4c · per-turn usage meta. */
  .cbv-turn-meta {
    display: flex; align-items: center; gap: 12px; padding: 0 2px;
    font-family: ui-monospace, "JetBrains Mono", monospace; font-size: 10.5px; color: var(--text-3);
  }

  /* ---- 5 · inputs strip (inset) ---- */
  .cbv-inputs-strip {
    display: flex; flex-direction: column; gap: 8px; padding: 11px 14px;
    border-radius: 10px; border: 1px solid var(--divider); background: var(--inset);
  }
  .cbv-inputs-toggle {
    align-self: flex-start; padding: 2px 6px; font-size: 11px; font-weight: 600;
    background: transparent; border: none; cursor: pointer; color: var(--text-3);
  }
  .cbv-inputs-fields { display: flex; flex-direction: column; gap: 8px; }
  .cbv-input-field { display: flex; flex-direction: column; gap: 3px; font-size: 12px; }
  .cbv-input-label {
    font-size: 10px; font-weight: 800; letter-spacing: 0.07em; text-transform: uppercase; color: var(--text-3);
  }
  .cbv-required-marker { color: var(--danger); }
  .cbv-input-field.cbv-input-missing > .cbv-input-label { color: var(--danger); }
  .cbv-input-field.cbv-input-disabled { opacity: 0.7; }

  /* ---- 6 · journal scope (inset) ---- */
  .cbv-journal-scope {
    display: flex; flex-wrap: wrap; gap: 6px 7px; align-items: center;
    padding: 11px 14px; border-radius: 10px; border: 1px solid var(--divider);
    background: var(--inset); font-size: 11px;
  }
  .cbv-journal-scope-label {
    font-size: 10px; font-weight: 800; letter-spacing: 0.07em; text-transform: uppercase; color: var(--text-3);
  }
  .cbv-journal-scope-chip {
    display: inline-flex; align-items: center; gap: 6px; padding: 2px 9px; border-radius: 999px;
    background: var(--k-lore-soft); border: 1px solid var(--k-lore-border);
    color: var(--k-lore-text); font-weight: 600;
    transition: background 250ms ease-out, border-color 250ms ease-out;
  }
  .cbv-journal-scope-chip::before {
    content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--k-lore);
  }
  .cbv-journal-scope-chip-depth1 { background: var(--surface); border-style: dashed; }
  .cbv-journal-scope-chip-depth1::before { background: #9a9cca; }
  .cbv-journal-scope-chip-fresh { border-color: var(--accent-soft2); }
  .cbv-journal-scope-chip-fresh::before { background: var(--accent); }
  .cbv-journal-scope-pip {
    font-size: 9px; font-weight: 700; border-radius: 4px;
    padding: 1px 4px; margin-left: 1px; line-height: 1.3;
  }
  .cbv-journal-scope-pip-fresh {
    color: var(--accent-strong); background: var(--accent-soft2);
  }
  .cbv-journal-scope-pip-depth1 {
    color: #6c6e9e; background: var(--k-lore-soft);
  }

  /* ---- 7 · cost estimate + 8 · TTL (inset) ---- */
  .cbv-estimate-strip,
  .cbv-ttl-strip {
    display: flex; flex-wrap: wrap; align-items: center; gap: 7px;
    padding: 11px 14px; border-radius: 10px; border: 1px solid var(--divider);
    background: var(--inset); font-size: 11px; color: var(--text-2);
  }
  .cbv-estimate-strip::before { content: "NEXT TURN EST."; }
  .cbv-ttl-strip::before { content: "CACHE TTL"; }
  .cbv-estimate-strip::before,
  .cbv-ttl-strip::before {
    font-size: 10px; font-weight: 800; letter-spacing: 0.07em; color: var(--text-3);
  }
  .cbv-estimate-tokens,
  .cbv-estimate-cost,
  .cbv-estimate-chip,
  .cbv-ttl-chip {
    display: inline-flex; align-items: center; gap: 5px; padding: 2px 9px; border-radius: 999px;
    background: var(--surface); border: 1px solid var(--divider); font-size: 11px;
  }
  .cbv-estimate-tokens,
  .cbv-estimate-cost { font-family: ui-monospace, "JetBrains Mono", monospace; }
  .cbv-estimate-chip { background: var(--accent-soft); border-color: var(--accent-soft2); color: var(--accent-strong); font-weight: 600; }
  .cbv-estimate-sep { display: none; }
  .cbv-ttl-chip.cbv-ttl-expired { background: var(--danger-soft); border-color: var(--danger-border); color: var(--danger); font-weight: 600; }

  /* ---- 10 · action row ---- */
  .cbv-action-row { display: flex; align-items: center; gap: 10px; justify-content: flex-end; }
  .cbv-action-row button {
    padding: 8px 14px; font-size: 12.5px; font-weight: 600; border-radius: 9px;
    border: 1px solid var(--border); background: var(--surface); color: var(--text-2); cursor: pointer;
  }
  .cbv-action-row button:hover { background: var(--inset); }
  .cbv-action-row button[disabled] { opacity: 0.5; cursor: default; }
  .cbv-action-row button.primary {
    background: var(--accent); color: #fff; border-color: var(--accent);
    box-shadow: 0 2px 6px var(--shadow2);
  }
  .cbv-action-row button.primary:hover { background: var(--accent-strong); }

  .cbv-foot {
    margin: 0; font-size: 11.5px; color: var(--text-3);
    border-top: 1px solid var(--divider); padding-top: 8px;
  }
</style>
