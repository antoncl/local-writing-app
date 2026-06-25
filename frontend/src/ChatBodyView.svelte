<!--
  ChatBodyView — body-region slot for entry types whose body_shape is
  "chat". Phase 4a skeleton: prop contract + bind:this surface only; the
  chat composer / messages / inputs strip / journal / cost / TTL / input
  card all land in Phases 4b–4c (see [[outstanding-work-2026-06-25-phase-3]]).

  The chat-as-node is passed in as `scene`. The actual ChatSession (with
  messages, journal, cost rollup, cache-write slots) is fetched by this
  view via the unified `/api/nodes/{id}` path — but that fetch belongs to
  Phase 4b. Today the body just renders a placeholder.

  Phase 4a target visual: a single muted card explaining the slot is
  reserved. Phase 4b replaces it with regions 1–10 from
  [[decisions-node-editor-body-spec]].
-->
<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import type {
    AssistantEntrySummary,
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

  // Suppress unused-prop warnings until Phase 4b wires these in.
  $: void metadataSchema;
  $: void promptEntries;
  $: void assistantEntries;
  $: void loreEntries;
  $: void structure;
  $: void defaultAssistantId;
  $: void implicitContextMatcher;
  $: void dispatch;

  // ---------- Public methods (called via bind:this from parent) ----------
  // Chats don't have a markdown body — messages are the body. NodeEditor's
  // emitChange wraps this for the unified `change` event; returning "" keeps
  // the existing save-path no-op-safe for chat-shape scenes.
  export function getBodyMarkdown(): string {
    return "";
  }
</script>

<div class="chat-body-view" role="region" aria-label="Chat">
  {#if scene}
    <div class="chat-placeholder">
      <div class="chat-placeholder-title">Chat body — placeholder</div>
      <div class="chat-placeholder-sub">
        Phase 4b will populate this region with the composer strip, messages, inputs, journal, cost estimate, TTL strip, and message input.
      </div>
      <div class="chat-placeholder-id">node id: <code>{scene.id}</code></div>
    </div>
  {/if}
</div>

<style>
  .chat-body-view {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
    padding: 16px;
  }

  .chat-placeholder {
    align-self: center;
    margin: auto;
    max-width: 520px;
    padding: 20px 24px;
    border: 1px dashed var(--color-border, #d0d4dc);
    border-radius: 10px;
    background: var(--color-surface-muted, #f7f8fb);
    color: var(--color-text-muted, #5b6172);
    text-align: center;
  }

  .chat-placeholder-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--color-text, #1f2330);
    margin-bottom: 6px;
  }

  .chat-placeholder-sub {
    font-size: 13px;
    line-height: 1.45;
    margin-bottom: 10px;
  }

  .chat-placeholder-id code {
    font-family: var(--font-mono, ui-monospace, "JetBrains Mono", monospace);
    font-size: 12px;
  }
</style>
