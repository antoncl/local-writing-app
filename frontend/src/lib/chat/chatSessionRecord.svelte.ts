// The chat's persisted-session record (#2528): the session fields a save echoes
// back (subject, staged set, lore gate, used-node picks, title, pinned, journal,
// cache-write stamps) plus hydrate / reset / payload-building. Kept out of
// ChatBodyView (its size cap); the view owns the transcript and composer state
// and hands the pieces it owns to `toPayload`.
//
// Reactivity is deliberately mixed and mirrors what the view had as locals: the
// plain fields are NOT reactive (making them so would re-run effects such as the
// quote-source effect and `estimate.getSubject`); only the fields that were
// `$state` / `$state.raw` stay so.

import { journalEntryKey } from "@/lib/chat/journal";
import { encodeChatInputDrafts } from "@/components/editor/body/chat/chatInputs";
import type {
  ChangedPick,
  ChatMessage,
  ChatSession,
  ChatSessionJournalEntry,
  SaveChatSessionRequest,
  SnapshotPick,
} from "@/lib/types";

/** The view-owned values a save payload also carries. */
export interface ChatPayloadOwn {
  history: ChatMessage[];
  promptEntryId: string;
  assistantId: string;
  systemPrompt: string;
  inputDrafts: Record<string, string>;
}

export class ChatSessionRecord {
  // ADR-0051 S5: the node this chat is about ("" for freeform chats). Plain.
  subject = "";
  // ADR-0055 §4: the mutation set this brainstorm owns (its `staged_set` edge). Plain.
  stagedSet = "";
  // ADR-0057 §2: the execution-derived lore gate.
  loreEnabled = $state(false);
  // ADR-0092 Amendment 1 §3: the prompt called no_lore().
  loreFree = $state(false);
  // ADR-0060 §2 / §5 / ADR-0093 §1: use(node) picks, hints, snapshots. Plain.
  usedNodeIds: string[] = [];
  usedNodeHints: Record<string, string> = {};
  usedSnapshots: SnapshotPick[] = [];
  // ADR-0067 S2: field descriptors the prompt registered. Reactive (#2513): a
  // chat that writes the scene's prose links no quotes.
  fieldContractStored = $state.raw<Record<string, unknown>[]>([]);
  title = "Untitled chat"; // plain
  pinned = false; // plain
  journal: ChatSessionJournalEntry[] = $state([]);
  // #1635: picked lore entries edited since the AI last saw them.
  changedPicks: ChangedPick[] = $state([]);
  cacheWriteTimes: Record<string, string> = $state({});
  // Cost is never held here (#1877); only the cache-write slot stamps still
  // ride the next persist. Plain.
  pendingCacheSlots: string[] = [];

  reset(): void {
    this.subject = "";
    this.stagedSet = "";
    this.loreEnabled = false;
    this.loreFree = false;
    this.usedNodeIds = [];
    this.usedNodeHints = {};
    this.usedSnapshots = [];
    this.fieldContractStored = [];
    this.title = "Untitled chat";
    this.pinned = false;
    this.journal = [];
    this.changedPicks = [];
    this.cacheWriteTimes = {};
    this.pendingCacheSlots = [];
  }

  /** Copy-not-shared so subsequent saves don't mutate the fetched session. */
  hydrate(session: ChatSession): void {
    this.title = session.title || "Untitled chat";
    this.pinned = session.pinned;
    this.journal = Array.isArray(session.journal) ? [...session.journal] : [];
    this.cacheWriteTimes = { ...(session.cache_write_times ?? {}) };
    this.subject = session.subject || "";
    this.stagedSet = session.staged_set || "";
    this.loreEnabled = session.lore_enabled ?? false;
    this.loreFree = session.lore_free ?? false;
    this.usedNodeIds = session.used_node_ids ?? [];
    this.usedNodeHints = session.used_node_hints ?? {};
    // ADR-0093 §1: hydration matters here — the save payload always sends
    // used_snapshots, so a missing hydrate would wipe a persisted chat's
    // snapshot picks with [] on the next save.
    this.usedSnapshots = session.used_snapshots ?? [];
    this.fieldContractStored = session.field_contract_stored ?? [];
    this.pendingCacheSlots = [];
  }

  /** Adopt the server's echo of a save. */
  applySaved(saved: ChatSession): void {
    this.title = saved.title;
    this.pinned = saved.pinned;
    this.cacheWriteTimes = { ...(saved.cache_write_times ?? {}) };
  }

  private deriveTitleFromHistory(history: ChatMessage[]): string | null {
    const firstUser = history.find((m) => m.role === "user");
    if (!firstUser) return null;
    const text = firstUser.content.trim().replace(/\s+/g, " ");
    if (!text) return null;
    return text.length > 50 ? text.slice(0, 50).trim() + "…" : text;
  }

  /** The save payload. Reads (does not clear) the pending cache slots — the
   * caller consumes them right after, before its await (#1564). */
  toPayload(own: ChatPayloadOwn): SaveChatSessionRequest {
    let title = this.title || "Untitled chat";
    if (title === "Untitled chat") {
      const derived = this.deriveTitleFromHistory(own.history);
      if (derived) title = derived;
    }
    const cache_write_slots =
      this.pendingCacheSlots.length > 0 ? [...this.pendingCacheSlots] : undefined;
    return {
      title,
      prompt_entry_id: own.promptEntryId,
      assistant_id: own.assistantId,
      system_prompt: own.systemPrompt,
      // ADR-0051 S5: echo the subject so per-turn saves never drop it (the scene
      // anchor rides here too, since a scene subject IS the anchored scene).
      subject: this.subject,
      // ADR-0055 §4: echo the owned mutation set so a per-turn save never drops
      // the edge (mirrors subject; the backend seeds it into context on resume).
      staged_set: this.stagedSet,
      // ADR-0057 §2: echo the lore gate, captured at the lock render. Mirrors
      // subject/staged_set — the backend preserves it when a save omits it, but
      // we always send the hydrated value so it never drifts.
      lore_enabled: this.loreEnabled,
      lore_free: this.loreFree,
      used_node_ids: this.usedNodeIds,
      used_node_hints: this.usedNodeHints,
      used_snapshots: this.usedSnapshots,
      field_contract_stored: this.fieldContractStored,
      pinned: this.pinned,
      context_items: [],
      messages: own.history.map((m) => ({
        role: m.role,
        content: m.content,
        thinking: m.thinking ?? "",
        truncated: !!m.truncated,
        input_truncated: !!m.input_truncated,
        stopped: !!m.stopped,
        usage: m.usage ?? null,
        cost_usd: m.cost_usd ?? null,
        // ADR-0076 decision 3: per-turn provenance, echoed through like usage/cost.
        provider: m.provider ?? null,
        model: m.model ?? null,
        latency_ms: m.latency_ms ?? null,
        // ADR-0086 §5: the lore-budget report, echoed through the same way.
        lore_fit: m.lore_fit ?? null,
        // S2: the per-turn journal chips must survive a reload — they are the
        // transcript's ambient auto-context signal now that the journal strip
        // is gone (the door carries the roster; the chips carry the moments).
        journal_added: m.journal_added ?? [],
        lore_updated: m.lore_updated ?? [],
      })),
      // Persist the per-input drafts so a chat round-trips its inputs across a
      // reload (#654); the view decodes them back on hydrate.
      inputs: encodeChatInputDrafts(own.inputDrafts),
      cache_write_slots,
    };
  }

  /** Take the pending cache slots and clear them, synchronously (#1564). */
  consumeCacheSlots(): string[] {
    const slots = this.pendingCacheSlots;
    this.pendingCacheSlots = [];
    return slots;
  }

  /** A failed save puts its consumed slots back, merged with any accrued since. */
  restoreCacheSlots(slots: string[]): void {
    if (slots.length > 0) {
      this.pendingCacheSlots = [...new Set([...slots, ...this.pendingCacheSlots])];
    }
  }

  /** Stamp a cache-write slot for the next persist (once per slot). */
  addCacheSlot(slot: string): void {
    if (!this.pendingCacheSlots.includes(slot)) {
      this.pendingCacheSlots = [...this.pendingCacheSlots, slot];
    }
  }

  appendJournal(added: ChatSessionJournalEntry[]): void {
    if (!added.length) return;
    // Keyed by (id, source), not id: a better-ranked re-mention is a second
    // journal entry for the same id (ADR-0086 Amendment 1).
    const existing = new Set(this.journal.map(journalEntryKey));
    const fresh = added.filter((e) => !existing.has(journalEntryKey(e)));
    if (!fresh.length) return;
    this.journal = [...this.journal, ...fresh];
  }
}
