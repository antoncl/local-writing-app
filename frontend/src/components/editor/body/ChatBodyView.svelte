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
  import {
    promptDeclaresCommit,
    promptEntriesForSurface,
    resolutionSceneIdFromInputs,
    type PromptResolutionContext,
  } from "@/lib/editor-core/promptResolution";
  import PlainTextEditor from "@/components/widgets/PlainTextEditor.svelte";
  import ChatTranscript from "@/components/editor/body/chat/ChatTranscript.svelte";
  import ChatInputsStrip from "@/components/editor/body/chat/ChatInputsStrip.svelte";
  import ChatJournalScope from "@/components/editor/body/chat/ChatJournalScope.svelte";
  import ChatEstimateStrip from "@/components/editor/body/chat/ChatEstimateStrip.svelte";
  import ChatComposerBar from "@/components/editor/body/chat/ChatComposerBar.svelte";
  import EntryDraftCard from "@/components/editor/body/chat/EntryDraftCard.svelte";
  import { formatCostEur } from "@/lib/utils/money";
  import type {
    AssistantEntrySummary,
    ChatMessage,
    ChatSession,
    ChatSessionJournalEntry,
    ChatSessionMessage,
    EditableDocument,
    LoreEntrySummary,
    PreviewMessage,
    PromptEntrySummary,
    SaveChatSessionRequest,
    StructureDocument,
  } from "@/lib/types";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { hiddenLibraryStore } from "@/lib/stores/hiddenLibrary";
  import { ChatCommitController } from "@/lib/stores/chatCommit.svelte";
  import { refreshChatSessions } from "@/lib/stores/chats";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { refreshReferenceIndexInBackground } from "@/lib/stores/references";
  import {
    assistantScopeTags,
    assistantSpeakerName,
    preferredAssistantForPrompt,
    scopedDefaultAssistantId,
    topmostMatchingAssistant,
  } from "@/lib/chat/assistantScope";
  import {
    coerceChatInputValue,
    decodeChatInputDrafts,
    encodeChatInputDrafts,
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
  // A non-error status from a commit — "no changes proposed", "ignored N
  // fields" — surfaced so a hidden out-of-band commit is never a silent no-op.
  let chatNotice: string | null = $state(null);
  let chatLastMeta: { provider: string; model: string; latency_ms: number } | null = $state(null);
  let chatInput = $state("");
  // True when the last send failed (error or empty output) and we restored
  // the typed text to the composer so the user can retry. Without this cue
  // the restore is indistinguishable from "the composer didn't clear" — the
  // core confusion behind #1037. Reset on the next send or any edit.
  let chatRewound = $state(false);
  let chatScrollEl: HTMLDivElement | null = $state(null);
  // Holds the rendered template for a prompt-bound chat (filled by
  // renderAndLockPromptTemplate on first send) or — for legacy sessions
  // — the freeform system message that was authored before chats had
  // to be prompt-bound. Empty for fresh chats; never user-editable now.
  let chatSystemPrompt = $state("");
  let chatPromptEntryId = $state("");
  let chatAssistantId = $state("");
  // Scene this chat was opened against (e.g. "invoke chat prompt" from a
  // ADR-0051 S5: the node this chat is about. Sent to the render as `subject`;
  // a scene subject IS the chat's anchored scene, so the backend derives the
  // `{{ scene }}` binding from it (the old target_scene_id folded into subject).
  // "" for freeform / Chats-pane chats.
  let chatSubject = "";
  // ADR-0055 §4: the mutation set this brainstorm owns (its `staged_set` edge),
  // set when a commit stages a timeline change (§4a). Echoed on every save so a
  // per-turn persist never drops it; seeded into the prompt context on resume
  // (backend, S3). "" until the chat stages a set.
  let chatStagedSet = "";
  // ADR-0057 §2: the execution-derived lore gate. Captured from the lock
  // render's preview response (whether the prompt actually called
  // relevant_lore()) and echoed on every save so a per-turn persist never
  // drops it. Drives whether the backend send path injects any lore at all.
  let chatLoreEnabled = false;
  let activeChatTitle = "Untitled chat";
  let activeChatPinned = false;
  let activeChatJournal: ChatSessionJournalEntry[] = $state([]);
  let activeChatJournalFreshIds = $state(new Set<string>());
  let activeChatCacheWriteTimes: Record<string, string> = $state({});
  // V2 cost accounting — pluck the delta off the streaming `done` event
  // and forward it to the backend on the next persistActiveChat.
  let pendingTurnCost: number | null = null;
  let pendingTurnCacheWriteSlots: string[] = [];

  // The composer instance, for the imperative clear on send (#1083).
  let composerRef: { setValue: (v: string) => void; focus: () => void } | null = $state(null);
  // The 👁 preview popover (and both picker chips) live in ChatComposerBar
  // (#1086); this view feeds it chatPreviewMessages below and the two pick
  // callbacks (pickPromptForChat / pickAssistantForChat).
  // The rendered messages from the last successful estimate fetch (system +
  // any templated initial turns). Null when no prompt is bound (freeform: no
  // system message) or the template hasn't rendered yet (unfilled inputs).
  let chatPreviewMessages: PreviewMessage[] | null = $state(null);

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

  // ADR-0046 entry-patch commit orchestration lives in its own per-instance rune
  // controller (#849); this view keeps the chat session + cost accounting and
  // feeds the controller its reactive inputs (further down, next to activeOutput).
  // Declared here — above the functions that call commit.reset() — so it is
  // defined before first use. The controller reaches back through `deps` for
  // history/cost/status, so `pendingTurnCost` and the chat status lines stay
  // component-owned.
  const commit = new ChatCommitController({
    getAssistantId: () => chatAssistantId,
    getHistory: () => chatHistory.map(({ role, content }) => ({ role, content })),
    addTurnCost: async (usd) => {
      pendingTurnCost = (pendingTurnCost ?? 0) + usd;
      await persistActiveChat();
    },
    setError: (message) => (chatError = message),
    setNotice: (message) => (chatNotice = message),
    entryTitle: (entryId) => loreEntries.find((entry) => entry.id === entryId)?.title ?? null,
    // The set this chat already owns, read at stage time so a re-stage refines it
    // in place (singular edge, §4) instead of minting an orphan.
    getStagedSetId: () => chatStagedSet,
    // ADR-0055 §4: a first stage points the chat's `staged_set` edge at the new
    // pinned set and persists — the chat owns it durably (resumable via the
    // backend's context seeding, S3).
    onStaged: async (setId) => {
      chatStagedSet = setId;
      await persistActiveChat();
    },
    // #983: a create-mode brainstorm launches before its entry exists, so its
    // `subject` can only be stamped here, when the entry is minted — making this
    // chat the entry's first conversation (ADR-0051 S2). Seeding the `entry`
    // input with the same id converts the chat into the revise brainstorm the
    // entry pane's ＋New would launch (isCreateBrainstorm keys off an empty
    // `entry` draft): a later commit in the resumed conversation refines this
    // entry instead of minting a duplicate, and the staging gate
    // (subjectLoreEntryType) derives from that draft too. Both persist in one
    // save; the refreshes mirror the create-with-subject launch path in
    // chatSessions (this save bypasses saveEditorPane's change-gated index
    // refresh), so the entry's Conversations panel lists the chat — with fresh
    // roster rows — without a reload.
    onCreated: async (entryId, entryTitle) => {
      chatSubject = entryId;
      chatInputDrafts = { ...chatInputDrafts, entry: entryId };
      // Retitle to the launched-with-subject convention ("<subject> — <prompt>",
      // chatSessions' launch naming) — but only while the chat still wears its
      // launch title (the bare prompt name), so a rename the user typed is
      // never clobbered. syncNodeTitle pushes the persisted title into the
      // pane's tab + header, which otherwise only hydrate on open.
      const promptTitle = activePromptEntry?.title ?? "";
      const retitle = !!promptTitle && activeChatTitle === promptTitle;
      if (retitle) activeChatTitle = `${entryTitle} — ${promptTitle}`;
      await persistActiveChat();
      if (retitle && scene?.id) editorPanes.syncNodeTitle(scene.id, activeChatTitle);
      void refreshChatSessions();
      refreshReferenceIndexInBackground();
    },
  });


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
    chatNotice = null;
    chatLastMeta = null;
    chatInput = "";
    chatRewound = false;
    chatSystemPrompt = "";
    chatPreviewMessages = null;
    chatPromptEntryId = "";
    chatAssistantId = "";
    chatSubject = "";
    chatStagedSet = "";
    chatLoreEnabled = false;
    activeChatTitle = "Untitled chat";
    activeChatPinned = false;
    activeChatJournal = [];
    activeChatJournalFreshIds = new Set();
    activeChatCacheWriteTimes = {};
    pendingTurnCost = null;
    pendingTurnCacheWriteSlots = [];
    chatInputDrafts = {};
    chatInputsHidden = false;
    commit.reset();
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
    chatSubject = session.subject || "";
    chatStagedSet = session.staged_set || "";
    chatLoreEnabled = session.lore_enabled ?? false;
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
    chatRewound = false;
    pendingTurnCost = null;
    pendingTurnCacheWriteSlots = [];
    commit.reset();
    // Restore per-prompt input drafts (#654) — the exact inverse of the
    // encodeChatInputDrafts persist in currentChatSessionPayload. A non-string
    // value (a typed seed the launch path wrote before the first persist) is
    // JSON-encoded back into the widget's string form.
    chatInputDrafts = decodeChatInputDrafts(
      (session as unknown as { inputs?: Record<string, unknown> }).inputs,
    );
    // Collapse the inputs strip by default once the chat is locked (has
    // turns) — the conversation owns the height; the user can re-expand to
    // inspect what was sent. Open it for fresh/unlocked chats still being set up.
    chatInputsHidden = (session.messages || []).length > 0;
  }

  // The two pick gestures stay here (they mutate session state + persist); the
  // picker chips themselves live in ChatComposerBar (#1086), which closes its
  // own dropdown before invoking these as callbacks.
  async function pickPromptForChat(entry: PromptEntrySummary): Promise<void> {
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

  async function pickAssistantForChat(id: string): Promise<void> {
    if (isLocked) return;
    chatAssistantId = id;
    await persistActiveChat();
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
      // ADR-0051 S5: echo the subject so per-turn saves never drop it (the scene
      // anchor rides here too, since a scene subject IS the anchored scene).
      subject: chatSubject,
      // ADR-0055 §4: echo the owned mutation set so a per-turn save never drops
      // the edge (mirrors subject; the backend seeds it into context on resume).
      staged_set: chatStagedSet,
      // ADR-0057 §2: echo the lore gate, captured at the lock render. Mirrors
      // subject/staged_set — the backend preserves it when a save omits it, but
      // we always send the hydrated value so it never drifts.
      lore_enabled: chatLoreEnabled,
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
      // Persist the per-input drafts so a chat round-trips its inputs across a
      // reload (#654) — previously hardcoded `{}`, which the first post-send
      // persist wrote over `session.inputs`, dropping the launch-seeded values
      // (a revise brainstorm's `entry`, a create brainstorm's `entry_type`) to
      // component state only. `applyChatSession` decodes these back into drafts.
      inputs: encodeChatInputDrafts(chatInputDrafts),
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
      onBodyChange?.();
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
    if (chatRunning || commit.committing) return;
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
    chatNotice = null;
    chatRewound = false;
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
    // Also clear imperatively (#1083): the reactive value-sync can wedge, so a
    // clear the user must always see can't depend on it alone.
    composerRef?.setValue("");
    chatRunning = true;
    const rewindUser = () => {
      if (userIdx >= 0) chatHistory = chatHistory.filter((_, i) => i !== userIdx);
      chatInput = text;
      composerRef?.setValue(text);
      // Only flag a rewind when there was text to restore — a prompt-bound
      // first turn ships with an empty composer, and re-blanking it is not a
      // "restored for retry" situation worth announcing.
      chatRewound = text.length > 0;
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
        // ADR-0051 S5: the chat's scene comes from its subject (backend-derived),
        // not a stored target_scene_id. An explicit scene_ref input still wins.
        target_scene_id: "",
        subject: chatSubject,
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
      // ADR-0057 §2: capture the execution-derived lore gate from this lock
      // render. Whether the template actually called relevant_lore() decides
      // whether the send path injects any lore; persisted with the system
      // prompt via the very next persistActiveChat.
      chatLoreEnabled = preview.lore_enabled ?? false;
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
    const ttlInterval = setInterval(() => { ttlTick += 1; }, 1000);
    return () => clearInterval(ttlInterval);
  });

  async function fetchChatEstimate(): Promise<void> {
    if (!chatPromptEntryId) {
      chatEstimate = null;
      chatPreviewMessages = null;
      return;
    }
    const entry = promptEntries.find((p) => p.id === chatPromptEntryId);
    if (!entry) {
      chatEstimate = null;
      chatPreviewMessages = null;
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
        // ADR-0051 S5: scene derives from the chat's subject (see first-send).
        target_scene_id: "",
        subject: chatSubject,
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
        chatPreviewMessages = null;
        return;
      }
      chatPreviewMessages = preview.messages ?? null;
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
  // Discovery context for the chat "Pick a prompt" list. Routing through the
  // shared promptEntriesForSurface seam (#682) drops this project's hidden
  // Library prompts and retires the duplicated inline output.kind filter.
  let promptDiscoveryCtx = $derived<PromptResolutionContext>({
    metadataSchema,
    promptEntries,
    loreEntries: [],
    availableScenes: [],
    hiddenPromptIds: $hiddenLibraryStore,
  });
  // The chat-routed pick list for ChatComposerBar (#1086): chat_panel prompts,
  // minus brainstorms (a `chat_panel` prompt with a `commit`, ADR-0054 §2) —
  // those launch contextually against a subject via Conversations ＋New, so
  // free-picking one here would give a Commit button with no target entry.
  let routedPromptEntries = $derived(
    promptEntriesForSurface(promptDiscoveryCtx, "chat_panel").filter(
      (entry) => !promptDeclaresCommit(promptDiscoveryCtx, entry),
    ),
  );
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
  // The active prompt's `output` (ADR-0054): `.kind` is the disposition; a
  // `.commit` marks a brainstorm that extracts to its `entry` target
  // (`.commit.review` how it's reviewed, `.commit.fields` what it extracts).
  let activeOutput = $derived(
    metadataSchema?.entry_types[activePromptEntry?.entry_type ?? ""]?.prompt?.context_strategy
      ?.output ?? null,
  );
  // The subject's entry_type when the revise target is a lore entity, else ""
  // (ADR-0055 §4a). A lore subject is time-travel-aware (ADR-0013), so only it
  // may stage a timeline mutation set; a scene / plot-card subject isn't in the
  // lore roster and leaves this "", gating staging off. Doubles as the staged
  // set's target_entry_type.
  let subjectLoreEntryType = $derived(
    loreEntries.find((entry) => entry.id === (chatInputDrafts["entry"] ?? "").trim())?.entry_type ??
      "",
  );
  // Feed the commit controller (declared up by the state block) its reactive
  // inputs each render — kept next to activeOutput, the derived it consumes.
  $effect.pre(() => {
    commit.output = activeOutput;
    commit.inputDrafts = chatInputDrafts;
    commit.running = chatRunning;
    commit.subjectEntryType = subjectLoreEntryType;
  });
  let assistantScope = $derived(assistantScopeTags(activePromptEntry));
  let scopedDefaultId = $derived(scopedDefaultAssistantId(assistantEntries, assistantScope, defaultAssistantId));
  let declaredInputs = $derived(activePromptEntry?.inputs ?? []);
  // A hidden input is launch-set, not user-authored (ADR-0046 §6.4) and has no
  // widget in the strip — so it must never gate Send, or an unset one would
  // disable the button with nothing for the user to fill.
  let missingRequiredInputs = $derived(declaredInputs.filter(
    (i) => i.required && !i.hidden && isInputMissing(i, chatInputDrafts[i.name]),
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
    <ChatComposerBar
      {isLocked}
      {chatPromptEntryId}
      {chatAssistantId}
      {promptEntries}
      {routedPromptEntries}
      {assistantEntries}
      {assistantScope}
      {scopedDefaultId}
      {chatSystemPrompt}
      {chatPreviewMessages}
      onPickPrompt={(entry) => void pickPromptForChat(entry)}
      onPickAssistant={(id) => void pickAssistantForChat(id)}
    />

    <ChatTranscript
      {chatHistory}
      {chatRunning}
      assistantName={assistantSpeakerName(chatAssistantId, assistantEntries, scopedDefaultId)}
      bind:scrollEl={chatScrollEl}
    />

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

    <ChatEstimateStrip estimate={chatEstimate} {ttlChips} />

    {#if chatLastMeta}
      <p class="cbv-meta">{chatLastMeta.provider} · {chatLastMeta.model} · {chatLastMeta.latency_ms} ms</p>
    {/if}
    {#if chatError}
      <p class="cbv-error">{chatError}</p>
    {/if}
    {#if chatNotice}
      <p class="cbv-notice">{chatNotice}</p>
    {/if}
    {#if chatRewound}
      <p class="cbv-notice cbv-rewound">Message not sent — restored below. Edit it or press Send to retry.</p>
    {/if}

    <PlainTextEditor
      bind:this={composerRef}
      class="cbv-input"
      value={chatInput}
      disabled={chatRunning || commit.committing}
      on:change={(e) => {
        chatInput = e.detail.value;
        chatRewound = false;
      }}
      on:keydown={(e) => handleChatInputKeydown(e.detail)}
      on:focus={() => onFocus?.()}
      placeholder="Message… (Ctrl/⌘+Enter to send)"
      ariaLabel="Chat message"
      minHeight={60}
      maxHeight={240}
      matcher={implicitContextMatcher}
    />

    {#if chatRunning || commit.committing}
      <p class="cbv-meta cbv-busy" aria-live="polite">
        <span class="cbv-busy-dot" aria-hidden="true"></span>
        {chatRunning ? "Sending…" : "Finalizing…"}
      </p>
    {/if}

    <div class="cbv-action-row">
      <button type="button" disabled={!chatHistory.length || chatRunning || commit.committing} onclick={clearChat}>Clear</button>
      {#if commit.isCreateBrainstorm}
        <!-- ADR-0046 §6.4 create mode: finalize into a whole proposed entry
             (out of band, hidden), reviewed in the card below — not a flip. -->
        <button
          type="button"
          class="cbv-commit"
          disabled={chatRunning || commit.committing || chatHistory.length === 0 || commit.draftProposal != null}
          title={commit.draftProposal != null
            ? "Review the proposed entry below"
            : "Finalize this brainstorm into a new entry to review"}
          onclick={() => void commit.commitDraft()}
        >
          {commit.committing ? "Drafting…" : "Propose new entry"}
        </button>
      {:else if commit.isCommitChat}
        <!-- ADR-0046 slice 3: finalize the brainstorm into a validated patch
             (out of band, hidden), reviewed on the target entry's pane. -->
        <button
          type="button"
          class="cbv-commit"
          disabled={chatRunning || commit.committing || !commit.commitTargetEntryId || chatHistory.length === 0}
          title={commit.commitTargetEntryId
            ? "Finalize this brainstorm and review the revised entry"
            : "This brainstorm has no target entry"}
          onclick={() => void commit.commitToEntry()}
        >
          {commit.committing ? "Committing…" : "Commit to entry"}
        </button>
        {#if commit.canStage}
          <!-- ADR-0055 §4a/§6: the timeline branch — same content, staged as a
               subject-pinned mutation set the writer later places in a scene,
               instead of overwriting the entry's base. Lore subject only. -->
          <button
            type="button"
            class="cbv-commit"
            disabled={chatRunning || commit.committing || chatHistory.length === 0}
            title="Stage this as a pending change pinned to the entry — place it from a scene later (it doesn't overwrite the entry)"
            onclick={() => void commit.stageToPendingSet()}
          >
            {commit.committing ? "Staging…" : "Stage as pending change"}
          </button>
        {/if}
      {/if}
      <button
        type="button"
        class="primary"
        disabled={chatRunning
          || commit.committing
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

    {#if commit.draftProposal}
      <!-- ADR-0046 §6.4: the whole proposed new entry, reviewed as a draft (no
           flip — nothing to diff against). Create runs the existing create path;
           Discard writes nothing. -->
      <EntryDraftCard
        draft={commit.draftProposal}
        dropped={commit.draftDropped}
        {metadataSchema}
        creating={commit.creatingDraft}
        onCreate={() => void commit.createDraft()}
        onDiscard={() => commit.reset()}
      />
    {/if}

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
  .cbv-notice,
  .cbv-meta {
    margin: 0;
    font-size: var(--fs-md);
    color: var(--text-3);
  }
  .cbv-error { color: var(--danger); }
  .cbv-notice { color: var(--text-2); }
  .cbv-meta { font-size: var(--fs-sm); }

  /* Retry cue — the composer text is back on purpose, not a failed clear. */
  .cbv-rewound { color: var(--text-2); }

  /* Composer-adjacent in-flight status — covers the first-turn render and the
     out-of-band commit, neither of which shows a streaming bubble. */
  .cbv-busy {
    display: flex;
    align-items: center;
    gap: 7px;
    color: var(--text-2);
    margin-top: 6px;
  }
  .cbv-busy-dot {
    width: 6px;
    height: 6px;
    border-radius: 999px;
    background: var(--accent);
    animation: cbv-busy-pulse 1.1s ease-in-out infinite;
  }
  @keyframes cbv-busy-pulse {
    0%, 100% { opacity: 0.35; }
    50% { opacity: 1; }
  }
  @media (prefers-reduced-motion: reduce) {
    .cbv-busy-dot { animation: none; }
  }

  /* The composer strip (prompt/assistant picker chips + 👁 preview popover) and
     its styles moved to chat/ChatComposerBar.svelte (#1086). */

  /* ---- 4 · messages ---- */
  /* The transcript (.cbv-messages) + its message atoms moved to
     chat/ChatTranscript.svelte (#99). The flex-child rule below keeps the
     composer + strips + input + action row at their natural height so only
     the transcript flexes; ChatTranscript's own .cbv-messages carries the
     flex: 1 1 0 that makes it scroll. */
  /* The inputs strip + journal scope carry their own flex: 0 0 auto now that
     they live in chat/ChatInputsStrip.svelte + chat/ChatJournalScope.svelte
     (#99). */
  /* ChatComposerBar sets flex: 0 0 auto on its own root (.cbv-composer-strip). */
  .cbv-action-row,
  .cbv-foot,
  :global(.chat-body-view > .cbv-input) {
    flex: 0 0 auto;
  }

  /* Cost-estimate + TTL strips (§7/§8) moved to chat/ChatEstimateStrip.svelte
     alongside the #1037 composer-feedback split. */

  /* ---- 10 · action row ---- */
  .cbv-action-row { display: flex; align-items: center; gap: 10px; justify-content: flex-end; }
  .cbv-action-row button {
    padding: 8px 14px; font-size: var(--fs-sm); font-weight: 600; border-radius: 9px;
    border: 1px solid var(--border); background: var(--surface); color: var(--text-2); cursor: pointer;
  }
  .cbv-action-row button:hover { background: var(--inset); }
  .cbv-action-row button[disabled] { opacity: 0.5; cursor: default; }
  .cbv-action-row button.primary {
    background: var(--accent); color: #fff; border-color: var(--accent);
    box-shadow: 0 2px 6px var(--shadow2);
  }
  .cbv-action-row button.primary:hover { background: var(--accent-strong); }
  /* Commit is an accent-outline verb — distinct from the filled primary Send,
     but clearly the consequential action on a brainstorm (ADR-0046 slice 2). */
  .cbv-action-row button.cbv-commit { border-color: var(--accent); color: var(--accent); }
  .cbv-action-row button.cbv-commit:hover {
    background: color-mix(in srgb, var(--accent) 10%, transparent);
  }

  .cbv-foot {
    margin: 0; font-size: var(--fs-sm); color: var(--text-3);
    border-top: 1px solid var(--divider); padding-top: 8px;
  }
</style>
