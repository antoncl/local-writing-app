<!--
  ChatBodyView — body-region slot for entry types whose body_shape is
  "chat". Phase 4b: read-only ownership slice — ChatBodyView fetches the
  ChatSession via the unified /api/nodes/{id} path, renders the composer
  chips + messages list + cost-total line. No send/clear yet; the
  message input, brief, preview popover, inputs strip, journal scope,
  cost-estimate strip, TTL strip, and the send/stream orchestration
  land in subsequent slices (see [[outstanding-work-2026-06-25-phase-3]]).

  Until Phase 4d switches the open-chat flow to the editor pane, this
  view is only reachable through the `?dev_chat_view=<chatId>` flag in
  App.svelte (used to visually verify the unified-path render).
-->
<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { api } from "./api";
  import { renderChatContent } from "./chatMessageRender";
  import { formatCostEur } from "./money";
  import type {
    AssistantEntrySummary,
    ChatSession,
    EditableDocument,
    LoreEntrySummary,
    MetadataSchema,
    PromptEntrySummary,
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

  // Suppress unused-prop warnings for props that Phase 4c+ will wire in.
  // (Inputs strip, journal scope, preview popover, implicit-context highlight
  // on the future message input — none of those exist yet in this slice.)
  $: void metadataSchema;
  $: void loreEntries;
  $: void structure;
  $: void implicitContextMatcher;
  $: void dispatch;

  let chatSession: ChatSession | null = null;
  let loading = false;
  let loadError: string | null = null;
  let loadedChatId: string | null = null;

  // Fetch the chat through the unified node-CRUD shim. Reactive on
  // scene.id so the view stays in sync when the editor pane swaps to
  // a different chat node.
  $: void maybeLoadChat(scene?.id ?? null);

  async function maybeLoadChat(chatId: string | null): Promise<void> {
    if (!chatId) {
      chatSession = null;
      loadError = null;
      loadedChatId = null;
      return;
    }
    if (chatId === loadedChatId) return;
    loading = true;
    loadError = null;
    try {
      const session = await api.readNode<ChatSession>(chatId);
      // Guard against late returns when the user already switched chats.
      if (scene?.id !== chatId) return;
      chatSession = session;
      loadedChatId = chatId;
    } catch (err) {
      if (scene?.id !== chatId) return;
      loadError = (err as Error).message || "Couldn't load chat.";
      chatSession = null;
    } finally {
      if (scene?.id === chatId) loading = false;
    }
  }

  function promptTitle(promptId: string): string {
    if (!promptId) return "Freeform";
    const entry = promptEntries.find((p) => p.id === promptId);
    return entry?.title ?? "Unknown prompt";
  }

  function assistantTitle(assistantId: string): string {
    if (!assistantId) {
      const def = assistantEntries.find((a) => a.id === defaultAssistantId);
      return def ? `Default (${def.title})` : "Default";
    }
    return assistantEntries.find((a) => a.id === assistantId)?.title ?? "Unknown assistant";
  }

  $: isLocked = (chatSession?.messages?.length ?? 0) > 0;
  $: messages = chatSession?.messages ?? [];

  // ---------- Public methods (called via bind:this from parent) ----------
  // Chats don't have a markdown body — messages are the body. NodeEditor's
  // emitChange wraps this for the unified `change` event; returning "" keeps
  // the existing save-path no-op-safe for chat-shape scenes.
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
      <span class="cbv-chip" class:cbv-chip-locked={isLocked} class:cbv-chip-assigned={!!chatSession.prompt_entry_id} title="Prompt (read-only in this slice; Phase 4c re-enables interactive picking)">
        <span class="cbv-chip-glyph" aria-hidden="true">✨</span>
        <strong>{promptTitle(chatSession.prompt_entry_id)}</strong>
        {#if isLocked}<span class="cbv-chip-lock" aria-label="locked">🔒</span>{/if}
      </span>
      <span class="cbv-chip" class:cbv-chip-locked={isLocked} title="Assistant (read-only in this slice)">
        <span class="cbv-chip-glyph" aria-hidden="true">🤖</span>
        <strong>{assistantTitle(chatSession.assistant_id)}</strong>
        {#if isLocked}<span class="cbv-chip-lock" aria-label="locked">🔒</span>{/if}
      </span>
    </div>

    <div class="cbv-messages" aria-label="Chat history">
      {#if messages.length === 0}
        <p class="cbv-empty">No messages yet.</p>
      {/if}
      {#each messages as message, i (i)}
        <div class="cbv-message cbv-message-{message.role}">
          <header class="cbv-message-role">{message.role}</header>
          {#if message.thinking}
            <details class="cbv-thinking">
              <summary>Thinking</summary>
              <div class="cbv-message-rendered">{@html renderChatContent(message.thinking)}</div>
            </details>
          {/if}
          {#if message.content}
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

    {#if chatSession.cost_usd_total != null}
      <footer class="cbv-foot">
        Session cost: {formatCostEur(chatSession.cost_usd_total)}
      </footer>
    {/if}

    <p class="cbv-readonly-hint">
      Phase 4b read-only preview. Send/clear and composer interactivity land in 4c.
    </p>
  {/if}
</div>

<style>
  .chat-body-view {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    padding: 12px 16px 16px;
    gap: 12px;
    overflow: hidden;
  }

  .cbv-empty,
  .cbv-error,
  .cbv-readonly-hint {
    margin: 0;
    font-size: 13px;
    color: var(--color-text-muted, #5b6172);
  }
  .cbv-error {
    color: var(--color-text-error, #b3261e);
  }
  .cbv-readonly-hint {
    border-top: 1px dashed var(--color-border, #d0d4dc);
    padding-top: 6px;
    font-style: italic;
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
  .cbv-chip-lock {
    font-size: 12px;
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

  .cbv-foot {
    margin: 0;
    font-size: 12px;
    color: var(--color-text-muted, #5b6172);
    border-top: 1px solid var(--color-border, #d0d4dc);
    padding-top: 6px;
  }
</style>
