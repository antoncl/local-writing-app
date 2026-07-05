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
  import { onMount, tick } from "svelte";
  import { api } from "@/lib/api";
  import { resolutionSceneIdFromInputs } from "@/lib/editor-core/promptResolution";
  import PlainTextEditor from "@/components/widgets/PlainTextEditor.svelte";
  import ChatTranscript from "@/components/editor/body/chat/ChatTranscript.svelte";
  import ChatInputsStrip from "@/components/editor/body/chat/ChatInputsStrip.svelte";
  import ChatJournalScope from "@/components/editor/body/chat/ChatJournalScope.svelte";
  import { formatCostEur, formatTokens } from "@/lib/utils/money";
  import type {
    AssistantEntrySummary,
    ChatMessage,
    ChatSession,
    ChatSessionJournalEntry,
    ChatSessionMessage,
    EditableDocument,
    LoreEntrySummary,
    PromptEntrySummary,
    SaveChatSessionRequest,
    StructureDocument,
  } from "@/lib/types";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { refreshChatSessions, refreshProjectCost } from "@/lib/stores/chats";
  import {
    assistantScopeTags,
    assistantTitle,
    partitionAssistants,
    preferredAssistantForPrompt,
    scopedDefaultAssistantId,
    topmostMatchingAssistant,
  } from "@/lib/chat/assistantScope";
  import {
    coerceChatInputValue,
    isInputMissing,
    seedInputDraftsFromEntry,
    ttlChipsFor,
  } from "@/components/editor/body/chat/chatInputs";

  
  interface Props {
    scene?: EditableDocument | null;
    promptEntries?: PromptEntrySummary[];
    assistantEntries?: AssistantEntrySummary[];
    loreEntries?: LoreEntrySummary[];
    structure?: StructureDocument | null;
    // Research tree (sibling to manuscript) — threaded to the picker.
    researchStructure?: StructureDocument | null;
    defaultAssistantId?: string;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    // Outbound events as callback props (#14: runes — replaces the dispatcher).
    // NB: this view declared an "open-chat" event historically but never
    // dispatched it (the editor-pane open-chat flow comes from ProseBodyView),
    // so it's intentionally dropped here.
    onBodyChange?: () => void;
    onFocus?: () => void;
  }

  let {
    scene = null,
    promptEntries = [],
    assistantEntries = [],
    loreEntries = [],
    structure = null,
    researchStructure = null,
    defaultAssistantId = "",
    implicitContextMatcher = null,
    onBodyChange,
    onFocus,
  }: Props = $props();


  let chatSession: ChatSession | null = $state(null);
  let loading = $state(false);
  let loadError: string | null = $state(null);
  let loadedChatId: string | null = null;

  // ---- chat working state (hydrated from chatSession on load) ----
  let chatHistory: ChatMessage[] = $state([]);
  let chatRunning = $state(false);
  let chatError: string | null = $state(null);
  let chatLastMeta: { provider: string; model: string; latency_ms: number } | null = $state(null);
  let chatInput = $state("");
  let chatScrollEl: HTMLDivElement | null = $state(null);
  // Holds the rendered template for a prompt-bound chat (filled by
  // renderAndLockPromptTemplate on first send) or — for legacy sessions
  // — the freeform system message that was authored before chats had
  // to be prompt-bound. Empty for fresh chats; never user-editable now.
  let chatSystemPrompt = $state("");
  let chatPromptEntryId = $state("");
  let chatAssistantId = $state("");
  // Scene this chat was opened against (e.g. "invoke chat prompt" from a
  // prose scene). Passed as the target scene when rendering the template
  // at first-send so prompts that reference `scene` resolve it. "" for
  // freeform / Chats-pane chats.
  let chatTargetSceneId = "";
  let activeChatTitle = "Untitled chat";
  let activeChatPinned = false;
  let activeChatJournal: ChatSessionJournalEntry[] = $state([]);
  let activeChatJournalFreshIds = $state(new Set<string>());
  let activeChatCacheWriteTimes: Record<string, string> = $state({});
  // V2 cost accounting — pluck the delta off the streaming `done` event
  // and forward it to the backend on the next persistActiveChat.
  let pendingTurnCost: number | null = null;
  let pendingTurnCacheWriteSlots: string[] = [];

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
  // The popover shows the rendered system_prompt — what the assistant
  // actually sees ahead of the conversation. For freeform chats that
  // IS the brief; for prompt-bound chats it's the post-render template.
  // Pure diagnostic — no fetch, just read-through of chatSystemPrompt.
  let chatPreviewPopoverOpen = $state(false);
  let chatPreviewBtnEl: HTMLButtonElement | null = $state(null);
  let chatPreviewPopoverEl: HTMLDivElement | null = $state(null);

  // ---- declared-inputs state (filled before first send for prompt-bound chats) ----
  // Per-input draft values keyed by input.name. JSON-encoded for list-shaped
  // types so storage stays string-uniform. Hydrated from session.inputs;
  // persisted on every edit so a half-configured chat survives reload.
  let chatInputDrafts: Record<string, string> = $state({});
  // Collapse the strip after first send to reclaim space — user can re-expand.
  let chatInputsHidden = $state(false);

  // ---- cost-estimate + TTL strip state ----
  // SLOT_TTL_SECONDS + ttlChipsFor moved to chat/chatInputs.ts (#99).
  // Tick counter — bumped every second by an onMount interval — so the
  // TTL chips' "remaining" recompute live. Anything else that wants a
  // 1Hz refresh can read this too.
  let ttlTick = $state(0);
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
  } | null = $state(null);
  // Stale-response guard: every fetch grabs ourToken = ++chatEstimateToken;
  // on resolve we drop the response if the token moved. Out-of-order
  // resolutions are common when the user types fast.
  let chatEstimateToken = 0;


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
    // Seed the assistant from the prompt: an explicit preferred pin wins;
    // otherwise the dynamic default = topmost assistant matching the prompt's
    // tag scope (ADR-0024). No scope + no pin → leave the current selection.
    const preferred = preferredAssistantForPrompt(entry);
    if (preferred) {
      chatAssistantId = preferred;
    } else {
      const tags = assistantScopeTags(entry);
      if (tags.length > 0) chatAssistantId = topmostMatchingAssistant(assistantEntries, tags)?.id ?? "";
    }
    // chatSystemPrompt stays empty until first-send; renderAndLockPromptTemplate
    // fills it in from api.aiPreview right before the first user turn ships
    // (deferred render lets the user edit input drafts freely).
    chatSystemPrompt = "";
    chatInputDrafts = seedInputDraftsFromEntry(entry);
    chatInputsHidden = false;
    await persistActiveChat();
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

  // defaultDraftFor / seedInputDraftsFromEntry / isInputMissing /
  // coerceChatInputValue moved to chat/chatInputs.ts (#99).

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
      onBodyChange?.();
      // A turn that accumulated cost moves the project-wide rollup chip. Write
      // through the cost store directly; the chip re-renders reactively (no
      // host signal needed — #14 Step 3).
      if (hadCost) void refreshProjectCost();
    } catch (e) {
      chatError = `Couldn't save chat: ${(e as Error).message}`;
    }
  }

  // Title rename feed from the pane header (NodeEditor owns the input;
  // ChatBodyView owns the title state so per-turn saves never revert it).
  // Debounced so typing doesn't hammer the backend; once the new title lands
  // we refresh the Chats roster directly so the pane re-renders (#14 Step 3).
  let titleSaveTimer: ReturnType<typeof setTimeout> | null = null;
  export function setTitleFromPane(next: string): void {
    if (!loadedChatId) return;
    if (next === activeChatTitle) return;
    activeChatTitle = next;
    if (titleSaveTimer) clearTimeout(titleSaveTimer);
    titleSaveTimer = setTimeout(() => {
      titleSaveTimer = null;
      void persistActiveChat().then(() => refreshChatSessions());
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
        resolution_scene_id: resolutionSceneIdFromInputs(entry, inputs),
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
        resolution_scene_id: resolutionSceneIdFromInputs(entry, inputs),
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

  // ttlChipsFor (per-slot TTL chips) moved to chat/chatInputs.ts (#99).
  // It reads ttlTick so chips recompute live, and activeChatCacheWriteTimes
  // so they refresh when a new turn stamps a slot.

  // ---------- Public methods (called via bind:this from parent) ----------
  export function getBody(): string {
    return "";
  }
  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  let metadataSchema = $derived($metadataSchemaStore);
  // Suppress unused-prop warnings for props Phase 4c+ wires in (preview
  // popover, inputs strip, future journal-scope rendering).
  $effect.pre(() => {
    void loreEntries;
  });
  $effect.pre(() => {
    void structure;
  });
  $effect.pre(() => {
    void maybeLoadChat(scene?.id ?? null);
  });
  let isLocked = $derived(chatHistory.length > 0);
  // The prompt entry currently bound to the chat, if any. Used to drive
  // declaredInputs + the first-send template render.
  let activePromptEntry = $derived(chatPromptEntryId
    ? promptEntries.find((p) => p.id === chatPromptEntryId) ?? null
    : null);
  // The active prompt's assistant scope + the dynamic default it implies:
  // topmost assistant matching the scope, else topmost overall (ADR-0024).
  let assistantScope = $derived(assistantScopeTags(activePromptEntry));
  let scopedDefaultId = $derived(scopedDefaultAssistantId(assistantEntries, assistantScope, defaultAssistantId));
  let assistantParts = $derived(partitionAssistants(assistantEntries, assistantPickerSearch, assistantScope));
  let declaredInputs = $derived(activePromptEntry?.inputs ?? []);
  let missingRequiredInputs = $derived(declaredInputs.filter(
    (i) => i.required && isInputMissing(i, chatInputDrafts[i.name]),
  ));
  let ttlChips = $derived(ttlChipsFor(activeChatCacheWriteTimes, ttlTick));
  // Re-fetch estimate when any input that drives it changes. Each dep
  // read on its own line so Svelte tracks them (see
  // [[feedback-svelte5-reactivity-traps]]).
  $effect.pre(() => {
    chatPromptEntryId;
    chatAssistantId;
    chatInputDrafts;
    promptEntries.length;
    void fetchChatEstimate();
  });
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
          onclick={() => void toggleChatPromptPicker()}
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
                onclick={() => void pickPromptForChat(entry)}
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
          onclick={() => void toggleAssistantPicker()}
          disabled={isLocked}
          aria-label="Assistant"
        >
          <span class="cbv-chip-glyph" aria-hidden="true">🤖</span>
          <strong>{assistantTitle(chatAssistantId, assistantEntries, scopedDefaultId)}</strong>
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
              onclick={() => void pickAssistantForChat("")}
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
          onclick={() => void pickAssistantForChat(assistant.id)}
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

    <ChatTranscript {chatHistory} {chatRunning} bind:scrollEl={chatScrollEl} />

    {#if declaredInputs.length > 0}
      <ChatInputsStrip
        {declaredInputs}
        {isLocked}
        bind:hidden={chatInputsHidden}
        {chatInputDrafts}
        {structure}
        {researchStructure}
        {loreEntries}
        {promptEntries}
        {implicitContextMatcher}
        onDraftChange={(name, value) => void updateChatInputDraft(name, value)}
      />
    {/if}

    {#if activeChatJournal.length > 0}
      <ChatJournalScope journal={activeChatJournal} freshIds={activeChatJournalFreshIds} />
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
      on:focus={() => onFocus?.()}
      placeholder="Message… (Ctrl/⌘+Enter to send)"
      ariaLabel="Chat message"
      minHeight={60}
      maxHeight={240}
      matcher={implicitContextMatcher}
    />

    <div class="cbv-action-row">
      <button type="button" disabled={!chatHistory.length || chatRunning} onclick={clearChat}>Clear</button>
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
        onclick={() => void sendChat()}
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

  /* Soft-partition affordances (ADR-0024): a label over the matching group and
     a hairline before the rest of the roster. */
  .cbv-picker-group-label {
    padding: 4px 8px 2px;
    font-size: 10px;
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
  /* The transcript (.cbv-messages) + its message atoms moved to
     chat/ChatTranscript.svelte (#99). The flex-child rule below keeps the
     composer + strips + input + action row at their natural height so only
     the transcript flexes; ChatTranscript's own .cbv-messages carries the
     flex: 1 1 0 that makes it scroll. */
  /* The inputs strip + journal scope carry their own flex: 0 0 auto now that
     they live in chat/ChatInputsStrip.svelte + chat/ChatJournalScope.svelte
     (#99). */
  .cbv-composer-strip,
  .cbv-estimate-strip,
  .cbv-ttl-strip,
  .cbv-action-row,
  .cbv-foot,
  :global(.chat-body-view > .cbv-input) {
    flex: 0 0 auto;
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
  .cbv-estimate-chip { background: var(--accent-soft); border-color: var(--accent-soft2); color: var(--accent-emphasis); font-weight: 600; }
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
