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
    effectivePromptInputs,
    entryIdFromPickValue,
    promptDeclaresCommit,
    promptEntriesForSurface,
    resolutionSceneIdFromInputs,
    type PromptResolutionContext,
  } from "@/lib/editor-core/promptResolution";
  import { coerceInputValue, isInputMissing } from "@/lib/utils/promptInputs";
  import { buildSelectorRoster, expandSelectorsInEncodedValue } from "@/lib/views/pickerSelectors";
  import PlainTextEditor from "@/components/widgets/PlainTextEditor.svelte";
  import ChatTranscript from "@/components/editor/body/chat/ChatTranscript.svelte";
  import ChatInputsStrip from "@/components/editor/body/chat/ChatInputsStrip.svelte";
  import ChatMetaLine from "@/components/editor/body/chat/ChatMetaLine.svelte";
  import ChatComposerBar from "@/components/editor/body/chat/ChatComposerBar.svelte";
  import EntryDraftCard from "@/components/editor/body/chat/EntryDraftCard.svelte";
  import type {
    AssistantEntrySummary,
    ChatEstimate,
    ChatMessage,
    ChatSession,
    ChatSessionJournalEntry,
    ChatSessionMessage,
    EditableDocument,
    LoreEntrySummary,
    PreviewCacheBlock,
    PreviewMessage,
    PromptEntrySummary,
    SaveChatSessionRequest,
    StructureDocument,
  } from "@/lib/types";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { cardEntriesStore } from "@/lib/stores/plotCards";
  import { hiddenLibraryStore } from "@/lib/stores/hiddenLibrary";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import { ChatCommitController } from "@/lib/stores/chatCommit.svelte";
  import { refreshChatSessions } from "@/lib/stores/chats";
  import { chatSessions } from "@/lib/stores/chatSessions.svelte";
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
    decodeChatInputDrafts,
    displayInputValues,
    encodeChatInputDrafts,
    endsInUserTurn,
    seedInputDraftsFromEntry,
    ttlChipsFor,
  } from "@/components/editor/body/chat/chatInputs";
  import { findNodeBySceneId } from "@/lib/utils/treeHelpers";
  import { structureNodeTitle } from "@/lib/utils/nodeTitle";
  import { isNearBottom, NEAR_BOTTOM_PX } from "@/lib/utils/scrollAnchor";

  
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
    // ADR-0076 S6: the serif document title, handed down from NodeEditor as a
    // snippet so title + setup chips share ChatComposerBar's one row. Optional —
    // only the chat mount passes it.
    titleField?: import("svelte").Snippet;
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
    titleField,
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
  // ADR-0076 S3: the in-flight stream's abort handle, so the Send button can
  // flip to Stop while streaming. Null when no stream is in flight.
  let chatAbort: AbortController | null = $state(null);
  let chatError: string | null = $state(null);
  // A non-error status from a commit — "no changes proposed", "ignored N
  // fields" — surfaced so a hidden out-of-band commit is never a silent no-op.
  let chatNotice: string | null = $state(null);
  let chatInput = $state("");
  // True when the last send failed (error or empty output) and we restored
  // the typed text to the composer so the user can retry. Without this cue
  // the restore is indistinguishable from "the composer didn't clear" — the
  // core confusion behind #1037. Reset on the next send or any edit.
  let chatRewound = $state(false);
  let chatScrollEl: HTMLDivElement | null = $state(null);
  // Stick-to-bottom (#1611): true while the reader is at/near the bottom, so
  // appends may follow the tail. Scrolling up releases it; the jump button and
  // any send re-pin it. Recomputed from geometry on every scroll.
  let pinnedToBottom = $state(true);
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
  let chatLoreEnabled = $state(false);
  // ADR-0060 §2: node ids the prompt selected via use(node). Captured from the
  // lock render's preview response and echoed on every save, exactly like
  // chatLoreEnabled — the backend unions them into its one lore selector.
  let chatUsedNodeIds: string[] = [];
  // ADR-0060 §5: per-node volatility priors from use(node, hint), mirrored beside
  // chatUsedNodeIds through the same capture/echo path.
  let chatUsedNodeHints: Record<string, string> = {};
  // ADR-0067 S2: the field descriptors the prompt registered via field_contract.
  // Captured from the lock render's preview response and echoed on every save,
  // mirrored beside chatUsedNodeIds — the commit reads this back instead of
  // re-rendering a separate extractor.
  let chatFieldContractStored: Record<string, unknown>[] = [];
  let activeChatTitle = "Untitled chat";
  let activeChatPinned = false;
  let activeChatJournal: ChatSessionJournalEntry[] = $state([]);
  let activeChatCacheWriteTimes: Record<string, string> = $state({});
  // V2 cost accounting — pluck the delta off the streaming `done` event
  // and forward it to the backend on the next persistActiveChat. $state (not
  // a plain let) so sessionCostUsd below reacts the instant the stream lands
  // the delta, not only after the round-trip persist resolves (ADR-0076 §6).
  let pendingTurnCost: number | null = $state(null);
  let pendingTurnCacheWriteSlots: string[] = [];

  // The composer instance, for the imperative clear on send (#1083).
  let composerRef: { setValue: (v: string) => void; focus: () => void } | null = $state(null);
  // The Context door (and both picker chips) live in ChatComposerBar (#1086);
  // this view feeds it chatPreviewMessages below and the two pick callbacks
  // (pickPromptForChat / pickAssistantForChat).
  // The rendered messages from the last successful estimate fetch (system +
  // any templated initial turns). Null when no prompt is bound (freeform: no
  // system message) or the template hasn't rendered yet (unfilled inputs).
  let chatPreviewMessages: PreviewMessage[] | null = $state(null);
  // The send-path cache blocks (system + attached lore tiers) WITH text — what
  // the model actually receives. The preview popover renders these so the lore
  // is visible; it lives only in a cache block, never the rendered template.
  let chatPreviewCacheBlocks: PreviewCacheBlock[] = $state([]);

  // ---- declared-inputs state (filled before first send for prompt-bound chats) ----
  // Per-input draft values keyed by input.name. JSON-encoded for list-shaped
  // types so storage stays string-uniform. Hydrated from session.inputs;
  // persisted on every edit so a half-configured chat survives reload.
  let chatInputDrafts: Record<string, string> = $state({});

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
  let chatEstimate: ChatEstimate | null = $state(null);
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
    // ADR-0067 S2: the chat's own node id — the commit runs as a cached
    // continuation of this chat, so the server reads back the field set its
    // lock render registered instead of rebuilding a separate contract.
    getChatId: () => scene?.id ?? "",
    addTurnCost: async (usd) => {
      pendingTurnCost = (pendingTurnCost ?? 0) + usd;
      await persistActiveChat();
    },
    setError: (message) => (chatError = message),
    setNotice: (message) => (chatNotice = message),
    entryTitle: (entryId) => loreTitle(entryId),
    // The commit publishes its review onto the entry's pane; bring that pane into
    // view (open or front) so the author sees the proposed-vs-current diff without
    // hunting for the review-dot. Only a lore subject is resolvable to an opener
    // from this pane's roster — a scene / plot-card subject keeps the notice-only
    // hand-off (its kind isn't known here). openLore focuses an already-open pane
    // or loads a fresh one; best-effort, so a navigation failure never breaks a
    // successful commit (the notice still names where the review went).
    revealEntry: (entryId) => {
      if (loreEntries.some((entry) => entry.id === entryId))
        void editorPanes.openLore(entryId).catch(() => {});
    },
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
      await tick();
      scrollToBottom();
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
    pinnedToBottom = true;
    chatError = null;
    chatNotice = null;
    chatInput = "";
    chatRewound = false;
    chatSystemPrompt = "";
    chatPreviewMessages = null;
    chatPreviewCacheBlocks = [];
    chatPromptEntryId = "";
    chatAssistantId = "";
    chatSubject = "";
    chatStagedSet = "";
    chatLoreEnabled = false;
    chatUsedNodeIds = [];
    chatUsedNodeHints = {};
    chatFieldContractStored = [];
    activeChatTitle = "Untitled chat";
    activeChatPinned = false;
    activeChatJournal = [];
    activeChatCacheWriteTimes = {};
    pendingTurnCost = null;
    pendingTurnCacheWriteSlots = [];
    chatInputDrafts = {};
    commit.reset();
  }

  // Mirrors App.svelte's applyChatSession (the source of truth for the
  // hydration shape). Copy-not-shared so subsequent saves don't mutate
  // the fetched session object.
  function applyChatSession(session: ChatSession) {
    activeChatTitle = session.title || "Untitled chat";
    activeChatPinned = session.pinned;
    activeChatJournal = Array.isArray(session.journal) ? [...session.journal] : [];
    activeChatCacheWriteTimes = { ...(session.cache_write_times ?? {}) };
    chatPromptEntryId = session.prompt_entry_id || "";
    chatAssistantId = session.assistant_id || "";
    chatSubject = session.subject || "";
    chatStagedSet = session.staged_set || "";
    chatLoreEnabled = session.lore_enabled ?? false;
    chatUsedNodeIds = session.used_node_ids ?? [];
    chatUsedNodeHints = session.used_node_hints ?? {};
    chatFieldContractStored = session.field_contract_stored ?? [];
    chatSystemPrompt = session.system_prompt || "";
    chatHistory = (session.messages || []).map((m: ChatSessionMessage) => ({
      role: m.role,
      content: m.content,
      truncated: !!m.truncated,
      stopped: !!m.stopped,
      thinking: m.thinking || undefined,
      journal_added: m.journal_added,
      usage: m.usage ?? null,
      cost_usd: m.cost_usd ?? null,
      // ADR-0076 decision 3: per-turn provenance, so it renders on the
      // transcript's own meta line instead of a floating cbv-meta paragraph.
      // Absent on messages persisted before this slice.
      provider: m.provider ?? null,
      model: m.model ?? null,
      latency_ms: m.latency_ms ?? null,
    }));
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
    await persistActiveChat();
  }

  async function pickAssistantForChat(id: string): Promise<void> {
    if (isLocked) return;
    chatAssistantId = id;
    await persistActiveChat();
  }

  // ADR-0076 S4: the lock doorway. Once a chat locks, its prompt/assistant/
  // inputs can't change (decision 8) — this reuses the Run flow's
  // create-seed-open chain to spin up a FRESH chat with the same setup
  // (prompt + assistant + input drafts), never the transcript.
  function newChatWithSetup(): void {
    // The doorway is only offered when a prompt is bound (see ComposerBar
    // canDoorway); guard anyway so the action is a no-op without a setup to
    // carry.
    if (!activePromptEntry) return;
    void chatSessions.openChatFromPromptEntry(
      activePromptEntry,
      encodeChatInputDrafts(chatInputDrafts),
      chatSubject || null,
      { assistantId: chatAssistantId },
    );
  }

  // defaultDraftFor / seedInputDraftsFromEntry / isInputMissing moved to
  // chat/chatInputs.ts (#99); value coercion is the shared coerceInputValue
  // (#1482 — the chat-local fork skipped container expansion).

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
      used_node_ids: chatUsedNodeIds,
      used_node_hints: chatUsedNodeHints,
      field_contract_stored: chatFieldContractStored,
      pinned: activeChatPinned,
      context_items: [],
      messages: chatHistory.map((m) => ({
        role: m.role,
        content: m.content,
        thinking: m.thinking ?? "",
        truncated: !!m.truncated,
        stopped: !!m.stopped,
        usage: m.usage ?? null,
        cost_usd: m.cost_usd ?? null,
        // ADR-0076 decision 3: per-turn provenance, echoed through like usage/cost.
        provider: m.provider ?? null,
        model: m.model ?? null,
        latency_ms: m.latency_ms ?? null,
        // S2: the per-turn journal chips must survive a reload — they are the
        // transcript's ambient auto-context signal now that the journal strip
        // is gone (the door carries the roster; the chips carry the moments).
        journal_added: m.journal_added ?? [],
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
    // #1564: CONSUME the pending cost delta + cache slots synchronously — build the
    // payload (which reads them) and clear them BEFORE the await. Otherwise a second
    // persist racing this one (e.g. setTitleFromPane's debounced rename, ungated by
    // chatRunning) reads the same still-set `pendingTurnCost` and re-sends the delta;
    // the backend appends an ai_invocations row per accepted delta, so the chat's cost
    // total is permanently inflated by a turn. Cleared here (not after the save) so the
    // race window closes; restored on failure so a failed save doesn't drop the cost.
    const payload = currentChatSessionPayload();
    const consumedCost = pendingTurnCost;
    const consumedSlots = pendingTurnCacheWriteSlots;
    pendingTurnCost = null;
    pendingTurnCacheWriteSlots = [];
    try {
      const saved = await api.saveNode<ChatSession>(chatId, payload);
      activeChatTitle = saved.title;
      activeChatPinned = saved.pinned;
      activeChatCacheWriteTimes = { ...(saved.cache_write_times ?? {}) };
      // Refresh our local snapshot of the persisted session — keeps the
      // cost-total footer accurate without re-fetching.
      chatSession = saved;
      onBodyChange?.();
    } catch (e) {
      // The save failed — put the consumed delta/slots back (merging anything accrued
      // meanwhile) so the next persist re-sends them rather than silently losing a turn.
      if (consumedCost != null) pendingTurnCost = (pendingTurnCost ?? 0) + consumedCost;
      if (consumedSlots.length > 0) {
        pendingTurnCacheWriteSlots = [...new Set([...consumedSlots, ...pendingTurnCacheWriteSlots])];
      }
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
  }

  // Stick-to-bottom (#1611) geometry + snap helpers, shared by the scroll
  // handler, streaming, post-send, chat-open, and the jump-to-latest button.
  function recomputePinned(): void {
    const el = chatScrollEl;
    if (!el) return;
    pinnedToBottom = isNearBottom(el.scrollTop, el.scrollHeight, el.clientHeight, NEAR_BOTTOM_PX);
  }

  // Snap the transcript to the tail and re-pin, in one synchronous step so the
  // pinned state always matches where the view actually is. Deliberately
  // instant, not smooth: "jump to latest" should land immediately, and a
  // pin-then-animate gap would hide the button before the view arrives.
  function scrollToBottom(): void {
    const el = chatScrollEl;
    if (!el) return;
    pinnedToBottom = true;
    el.scrollTop = el.scrollHeight;
  }

  // Keep a pinned reader glued to the tail through ANY content growth — each
  // streamed token, and the async KaTeX/markdown render that grows a freshly
  // opened chat AFTER `tick()` has already run. One observer over all growth
  // (vs. a per-chunk scroll call) also covers the on-open settle, and it never
  // fights a reader who scrolled up — their scroll cleared pinnedToBottom. (#1611)
  $effect(() => {
    const el = chatScrollEl;
    if (!el) return;
    const obs = new MutationObserver(() => {
      if (pinnedToBottom) el.scrollTop = el.scrollHeight;
    });
    obs.observe(el, { childList: true, subtree: true, characterData: true });
    return () => obs.disconnect();
  });

  async function streamAssistantReply(onError: () => void): Promise<void> {
    chatHistory = [...chatHistory, { role: "assistant", content: "" }];
    const idx = chatHistory.length - 1;
    let errored = false;
    // ADR-0076 S3: one abort handle per stream, so Stop can cancel the fetch
    // mid-flight. Cleared in `finally` regardless of how the stream ends.
    chatAbort = new AbortController();
    try {
      for await (const ev of api.aiChatStream(
        {
          assistant_id: chatAssistantId || null,
          system_prompt: chatSystemPrompt,
          messages: chatHistory.slice(0, idx).map(({ role, content }) => ({ role, content })),
          chat_id: scene?.id ?? null,
        },
        chatAbort.signal,
      )) {
        if (ev.type === "delta") {
          chatHistory[idx].content += ev.text;
          chatHistory = chatHistory;
        } else if (ev.type === "thinking") {
          chatHistory[idx].thinking = (chatHistory[idx].thinking ?? "") + ev.text;
          chatHistory = chatHistory;
        } else if (ev.type === "done") {
          chatHistory[idx].truncated = ev.truncated;
          if (Array.isArray(ev.journal_added) && ev.journal_added.length > 0) {
            chatHistory[idx].journal_added = ev.journal_added;
            appendToActiveChatJournal(ev.journal_added);
          }
          if (ev.usage) chatHistory[idx].usage = ev.usage;
          if (typeof ev.cost_usd === "number") {
            chatHistory[idx].cost_usd = ev.cost_usd;
            // Only a POSITIVE delta accrues toward the session total — the
            // backend refuses <= 0 deltas (`_record_chat_cost_delta`), and a
            // zero-priced turn must not fabricate a "session €0.00" for a chat
            // whose true total is unknown/None (#697). The per-message stamp
            // above keeps the honest 0 for the turn itself.
            if (ev.cost_usd > 0) pendingTurnCost = (pendingTurnCost ?? 0) + ev.cost_usd;
          }
          if (ev.usage && ev.usage.cache_write_tokens > 0) {
            if (!pendingTurnCacheWriteSlots.includes("system")) {
              pendingTurnCacheWriteSlots = [...pendingTurnCacheWriteSlots, "system"];
            }
          }
          // ADR-0076 decision 3: stamp provider/model/latency onto the message
          // itself, same as usage/cost above — it renders on the transcript's
          // own meta line now instead of a floating cbv-meta paragraph below it.
          chatHistory[idx].provider = ev.provider;
          chatHistory[idx].model = ev.model;
          chatHistory[idx].latency_ms = ev.latency_ms;
          chatHistory = chatHistory;
        } else if (ev.type === "error") {
          errored = true;
          chatError = ev.error || "Unknown error";
          chatHistory = chatHistory.slice(0, idx);
          onError();
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        // ADR-0076 S3: a deliberate Stop, not a network error — keep the
        // partial (if any), never rewind, never route through chatError.
        if (chatHistory[idx] && !chatHistory[idx].content && !chatHistory[idx].thinking) {
          // Nothing streamed yet — drop the empty assistant turn silently.
          chatHistory = chatHistory.slice(0, idx);
        } else if (chatHistory[idx]) {
          chatHistory[idx].stopped = true;
          chatHistory = chatHistory;
        }
        void persistActiveChat();
        return;
      }
      throw err;
    } finally {
      chatAbort = null;
    }
    if (!errored && !chatHistory[idx]?.content && !chatHistory[idx]?.thinking) {
      chatHistory = chatHistory.slice(0, idx);
      chatError = "Model returned empty output.";
      onError();
    } else if (!errored) {
      void persistActiveChat();
    }
  }

  function stopChat(): void {
    chatAbort?.abort();
  }

  // #1436: a self-contained prompt is submittable with an EMPTY composer iff its
  // FINAL rendered section is a user turn — the rendered conversation then ends in
  // a user message the provider can answer (the system prompt is a separate wire
  // field, so system-only prose can't be sent alone → "messages must not be
  // empty"). Read off the estimate preview so the send button knows before the
  // send-time lock render.
  const promptEndsInUserTurn = $derived(endsInUserTurn(chatPreviewMessages));

  async function sendChat() {
    if (chatRunning || commit.committing) return;
    if (sendBlockingInputs.length > 0) {
      chatError = `Missing required: ${sendBlockingInputs.map((i) => i.label || i.name).join(", ")}.`;
      return;
    }
    const text = chatInput.trim();
    // Empty composer text is allowed only when the chat is bound to a
    // prompt AND has no history yet — i.e. the template IS the message.
    // Mirrors sendChat in App.svelte (McKee-style self-contained prompts
    // shouldn't force the user to type "Do it").
    const isFirstTurnFromPrompt = !!activePromptEntry && chatHistory.length === 0;
    if (!text && !isFirstTurnFromPrompt) return;
    chatError = null;
    chatNotice = null;
    chatRewound = false;
    // First-send template render: render + lock whenever the chat is bound to a
    // prompt that hasn't been rendered yet (#1436 — no longer gated on declared
    // inputs, so an input-less self-contained prompt also applies its system
    // prompt and contributes any `{% role %}` turns, incl. a trailing user turn,
    // to chatHistory).
    if (activePromptEntry && !chatSystemPrompt) {
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
    // #1436: after the first-send render, an empty composer is valid only when
    // the prompt supplied a trailing user turn (chatHistory now ends in `user`) —
    // else the rendered conversation has no user message for the model to answer,
    // so there is nothing to send. The button reflects this via
    // promptEndsInUserTurn; this is the authoritative backstop (the real render).
    if (!text && !endsInUserTurn(chatHistory)) return;
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
    await tick();
    scrollToBottom();
    try {
      await streamAssistantReply(rewindUser);
    } catch (e) {
      chatError = (e as Error).message;
      rewindUser();
    } finally {
      chatRunning = false;
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
    for (const input of effectivePromptInputs(entry)) {
      const raw = chatInputDrafts[input.name] ?? "";
      let coerced = coerceInputValue(raw, input.type);
      if (input.type === "context_pick")
        coerced = expandSelectorsInEncodedValue(coerced as string, selectorRoster);
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
      chatUsedNodeIds = preview.used_node_ids ?? [];
      chatUsedNodeHints = preview.used_node_hints ?? {};
      chatFieldContractStored = preview.field_contract_stored ?? [];
      if (initialTurns.length > 0) chatHistory = [...initialTurns];
      return true;
    } catch (e) {
      chatError = `Couldn't render prompt template: ${(e as Error).message}`;
      return false;
    }
  }

  const runClear = async () => {
    chatHistory = [];
    chatError = null;
    // Reset cost-delta + cache-slot stamping so the next persist starts clean.
    pendingTurnCost = null;
    pendingTurnCacheWriteSlots = [];
    // Persist the clear so a reload doesn't resurrect the messages.
    await persistActiveChat();
  };

  // ADR-0076 decision 4: Clear is destructive and irreversible once persisted
  // — confirm every time (no `dontShowAgainKey`; "safe hands").
  function clearChat() {
    const n = chatHistory.length;
    confirmService.request({
      title: `Delete ${n} message${n === 1 ? "" : "s"}?`,
      message: "This clears the conversation and persists immediately. The prompt, assistant, and inputs will unlock.",
      confirmLabel: "Clear chat",
      destructive: true,
      cannotBeUndone: true,
      onConfirm: runClear,
    });
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
    // Invalidate any in-flight fetch FIRST — including on the early returns.
    // Bumping after them let a previous chat's response land after a switch to
    // a promptless chat (same token, isLocked false) and write that chat's
    // lore gate onto this one (S2 review).
    const ourToken = ++chatEstimateToken;
    if (!chatPromptEntryId) {
      chatEstimate = null;
      chatPreviewMessages = null;
      chatPreviewCacheBlocks = [];
      return;
    }
    const entry = promptEntries.find((p) => p.id === chatPromptEntryId);
    if (!entry) {
      chatEstimate = null;
      chatPreviewMessages = null;
      chatPreviewCacheBlocks = [];
      return;
    }
    const inputs: Record<string, unknown> = {};
    for (const declared of effectivePromptInputs(entry)) {
      const raw = chatInputDrafts[declared.name] ?? "";
      let coerced = coerceInputValue(raw, declared.type);
      if (declared.type === "context_pick")
        coerced = expandSelectorsInEncodedValue(coerced as string, selectorRoster);
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
        chatPreviewCacheBlocks = [];
        return;
      }
      chatPreviewMessages = preview.messages ?? null;
      // Keep the block TEXT (the estimate strip strips it to label/tokens); the
      // preview popover needs it to show the attached lore.
      chatPreviewCacheBlocks = preview.cache_blocks ?? [];
      // ADR-0076 S2: pre-lock, this fetch is the only place the lore gate is
      // known — mirror the lock render's capture (renderAndLockPromptTemplate)
      // so the Context door's "lore-enabled" annotation is live while the
      // writer is still filling inputs. Once the lock render has captured the
      // authoritative value it owns the field — guard on the SAME signals the
      // lock sets (system prompt) plus the in-flight send, not just isLocked:
      // during the first send's persist await the history is still empty, so a
      // stale estimate resolving in that window would clobber the lock's
      // capture and persist a wrong gate (S2 review).
      if (!isLocked && !chatRunning && !chatSystemPrompt) {
        chatLoreEnabled = preview.lore_enabled ?? false;
      }
      chatEstimate = {
        tokens: preview.estimated_tokens ?? 0,
        cost_usd: preview.estimated_cost_usd ?? null,
        caching_style: preview.caching_style ?? null,
        // The chat's meta line reads only tokens/cost/caching_style; the door
        // reads the FULL blocks via chatPreviewCacheBlocks above. Nothing chat-
        // side consumes this field (it exists for InputsDialog's shared type).
        cache_blocks: [],
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
  // The roster a context_pick SELECTOR (tag / saved view / plotline) evaluates
  // against at invocation (ADR-0074 slice 5/6). Built from what this surface has in
  // scope; plot cards come from the app-wide store (the plot roster is cards).
  let selectorRoster = $derived(
    buildSelectorRoster({ schema: metadataSchema, structure, loreEntries, assistantEntries, cardEntries: $cardEntriesStore }),
  );
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
  // The chat-routed pick list for ChatComposerBar (#1086): conversation prompts,
  // minus brainstorms (a conversation prompt with a `commit`, ADR-0054 §2 / ADR-0065)
  // — those launch contextually against a subject via Conversations ＋New, so
  // free-picking one here would give a Commit button with no target entry.
  let routedPromptEntries = $derived(
    promptEntriesForSurface(promptDiscoveryCtx, "conversation").filter(
      (entry) => !promptDeclaresCommit(promptDiscoveryCtx, entry),
    ),
  );
  $effect.pre(() => {
    void maybeLoadChat(scene?.id ?? null);
  });
  let isLocked = $derived(chatHistory.length > 0);
  // The prompt entry currently bound to the chat, if any. Used to drive
  // declaredInputs + the first-send template render.
  let activePromptEntry = $derived(chatPromptEntryId
    ? promptEntries.find((p) => p.id === chatPromptEntryId) ?? null
    : null);
  // The active prompt's `output` (ADR-0054): routing is `outputHandlerFor(output.handler)`
  // (`PromptOutput` has no `.kind`); a `.commit` marks a brainstorm that extracts to its
  // `entry` target (`.commit.review` = how it's reviewed; WHAT it extracts is authored in the
  // prompt's own `field_contract` loop, read back at commit — ADR-0067 S2).
  // Read off the prompt INSTANCE's own `context_strategy` (ADR-0065 S3) — never
  // the entry-type's, which no longer carries per-prompt behavior.
  let activeOutput = $derived(activePromptEntry?.context_strategy?.output ?? null);
  // The subject's entry_type when the revise target is a lore entity, else ""
  // (ADR-0055 §4a). A lore subject is time-travel-aware (ADR-0013), so only it
  // may stage a timeline mutation set; a scene / plot-card subject isn't in the
  // lore roster and leaves this "", gating staging off. Doubles as the staged
  // set's target_entry_type.
  // The `entry` draft may be an encoded context_pick list (revise launches
  // seed one) or a legacy bare id — read it through the shared decoder, not
  // as a raw string (#1482). Decoded once, not once per lore entry inside find.
  let entryDraftTargetId = $derived(entryIdFromPickValue(chatInputDrafts["entry"]));
  let subjectLoreEntryType = $derived(
    loreEntries.find((entry) => entry.id === entryDraftTargetId)?.entry_type ?? "",
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
  let declaredInputs = $derived(activePromptEntry ? effectivePromptInputs(activePromptEntry) : []);
  // ADR-0046 §6.4 create mode: the revise-target picker (`entry`) is meaningless
  // when drafting a NEW entry — and filling it would silently flip the flow to
  // revise — so drop it from the strip. The hidden `entry_type` still reaches the
  // template via the persisted drafts; revise mode keeps the picker (#695).
  let strippedInputs = $derived(
    commit.isCreateBrainstorm ? declaredInputs.filter((i) => i.name !== "entry") : declaredInputs,
  );
  // The one lore-title lookup — shared by titleFor and the commit
  // controller's entryTitle (whose null result is a KIND discriminator for
  // its "the scene"/"the entry" phrasing, so it stays lore-only).
  function loreTitle(id: string): string | null {
    return loreEntries.find((entry) => entry.id === id)?.title ?? null;
  }
  // ADR-0076 S2: id → title, for the Context door's drill-down (tier member
  // titles) and its locked-inputs section. Lore covers the common ref target;
  // plot cards come from the app-wide store; a scene ref resolves through the
  // manuscript structure (its front-matter `id` IS the structure node's
  // `scene_id`, not the node id — #201) via the one display-title resolver
  // (`structureNodeTitle` honors a schema `display_template`, like every
  // other surface that labels a manuscript node).
  function titleFor(id: string): string | null {
    const lore = loreTitle(id);
    if (lore) return lore;
    const card = $cardEntriesStore.find((c) => c.id === id)?.title;
    if (card) return card;
    const sceneNode = structure ? findNodeBySceneId(structure.root, id) : null;
    return sceneNode ? structureNodeTitle(sceneNode, metadataSchema) : null;
  }
  // ADR-0076 S2: the Context door's "Inputs (locked)" section — filled draft
  // values as titled text, read-only. Only meaningful once locked (pre-lock the
  // inputs strip IS the form); rendered by ChatComposerBar.
  let lockedInputDisplays = $derived(
    isLocked ? displayInputValues(strippedInputs, chatInputDrafts, { titleFor }) : [],
  );
  // A hidden input is launch-set, not user-authored (ADR-0046 §6.4) and has no
  // widget in the strip — so it must never gate Send, or an unset one would
  // disable the button with nothing for the user to fill.
  let missingRequiredInputs = $derived(declaredInputs.filter(
    (i) => i.required && !i.hidden && isInputMissing(i, chatInputDrafts[i.name]),
  ));
  // Required inputs gate Send only PRE-lock — the first send is what renders
  // the template from them. Post-lock the system prompt is frozen, so a
  // later drift (a prompt edited to add a required input) must not brick a
  // locked chat whose inputs form is no longer mounted (S2 review).
  let sendBlockingInputs = $derived(isLocked ? [] : missingRequiredInputs);
  let ttlChips = $derived(ttlChipsFor(activeChatCacheWriteTimes, ttlTick));
  // The session-cost line's number (ADR-0076 decision 6): the persisted
  // projection plus the not-yet-persisted delta. A stream `done` sets
  // pendingTurnCost before the persist round-trip starts, and persistActiveChat
  // swaps in the save response's total (which now carries the same log
  // projection the read path computes) while nulling the pending delta in the
  // same tick — so the display never lags the transcript. Known residual
  // (#1564): two persists in flight at once can each carry the same
  // cost_delta_usd to the backend; that is a persistence race, not a display
  // one — this derived shows whatever the backend recorded.
  let sessionCostUsd = $derived.by(() => {
    const persisted = chatSession?.cost_usd_total ?? null;
    return persisted != null || pendingTurnCost != null ? (persisted ?? 0) + (pendingTurnCost ?? 0) : null;
  });
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
      {titleField}
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
      previewCacheBlocks={chatPreviewCacheBlocks}
      loreEnabled={chatLoreEnabled}
      journal={activeChatJournal}
      {lockedInputDisplays}
      {titleFor}
      onPickPrompt={(entry) => void pickPromptForChat(entry)}
      onPickAssistant={(id) => void pickAssistantForChat(id)}
      onNewChatWithSetup={() => newChatWithSetup()}
    />

    <ChatTranscript
      {chatHistory}
      {chatRunning}
      assistantName={assistantSpeakerName(chatAssistantId, assistantEntries, scopedDefaultId)}
      bind:scrollEl={chatScrollEl}
      onScroll={recomputePinned}
      showJumpToLatest={!pinnedToBottom}
      onJumpToLatest={() => scrollToBottom()}
    />

    {#if !isLocked && strippedInputs.some((i) => !i.hidden)}
      <ChatInputsStrip
        declaredInputs={strippedInputs}
        {chatInputDrafts}
        {structure}
        {researchStructure}
        {loreEntries}
        {promptEntries}
        {implicitContextMatcher}
        onDraftChange={(name, value) => void updateChatInputDraft(name, value)}
      />
    {/if}

    <ChatMetaLine estimate={chatEstimate} {ttlChips} {sessionCostUsd} />

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
      onChange={(next) => {
        chatInput = next;
        chatRewound = false;
      }}
      onKeydown={handleChatInputKeydown}
      onFocus={() => onFocus?.()}
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
      <button type="button" class="cbv-clear" disabled={!chatHistory.length || chatRunning || commit.committing} onclick={clearChat}>Clear</button>
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
      {#if chatRunning}
        <!-- ADR-0076 decision 5: the primary button flips to Stop while a
             reply streams. Disabled until the stream's AbortController exists
             (chatAbort) so the control is honest — during the brief first-send
             template render, chatRunning is already true but there is nothing
             to abort yet, and a live "Stop" that no-ops would be a lie. -->
        <button type="button" class="primary" disabled={!chatAbort} onclick={() => stopChat()}>Stop</button>
      {:else}
        <button
          type="button"
          class="primary"
          disabled={commit.committing
            || sendBlockingInputs.length > 0
            || (!chatInput.trim() && !(activePromptEntry && chatHistory.length === 0 && promptEndsInUserTurn))}
          title={sendBlockingInputs.length > 0
            ? `Fill required input${sendBlockingInputs.length > 1 ? "s" : ""}: ${sendBlockingInputs.map((i) => i.label || i.name).join(", ")}`
            : (!chatInput.trim() && activePromptEntry && chatHistory.length === 0 && promptEndsInUserTurn)
              ? "Send the prompt as-is — it ends with a user turn"
              : ""}
          onclick={() => void sendChat()}
        >
          Send
        </button>
      {/if}
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

  /* The composer strip (prompt/assistant picker chips + Context door) and
     its styles moved to chat/ChatComposerBar.svelte (#1086). */

  /* ---- 4 · messages ---- */
  /* The transcript (.cbv-transcript > .cbv-messages) + its message atoms moved
     to chat/ChatTranscript.svelte (#99; wrapper added #1611). The flex-child
     rule below keeps the composer + strips + input + action row at their
     natural height so only the transcript flexes; ChatTranscript's own
     .cbv-transcript now carries the flex: 1 1 0, with the inner .cbv-messages
     (min-height: 0) scrolling and hosting the floating jump-to-latest button. */
  /* The inputs strip carries its own flex: 0 0 auto in chat/ChatInputsStrip.svelte
     (#99). The journal-scope strip retired into the Context door (ADR-0076 S2). */
  /* ChatComposerBar sets flex: 0 0 auto on its own root (.cbv-composer-strip). */
  .cbv-action-row,
  :global(.chat-body-view > .cbv-input) {
    flex: 0 0 auto;
  }

  /* Cost-estimate + TTL strips (§7/§8) moved to chat/ChatMetaLine.svelte,
     collapsed into one metadata line alongside the session-cost footer
     (ADR-0076 S1) — replacing the #1037 composer-feedback split. */

  /* ---- 10 · action row ---- */
  .cbv-action-row { display: flex; align-items: center; gap: 10px; justify-content: flex-end; }
  /* ADR-0076 decision 4: Clear is left-anchored, pushing the whole
     commit/Send cluster to the right — Clear and Send are never adjacent. */
  .cbv-clear { margin-inline-end: auto; }
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
</style>
