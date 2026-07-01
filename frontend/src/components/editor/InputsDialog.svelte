<script lang="ts" module>
  // Lives in <script module> because Svelte 5 disallows type exports from
  // instance scripts.
  export type InputsDialogEstimate = {
    tokens: number;
    cost_usd: number | null;
    caching_style: "none" | "auto" | "explicit" | null;
    cache_blocks: { label: string; tokens: number; cache_break_after: boolean }[];
  };
</script>

<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import PromptInputField from "@/components/widgets/PromptInputField.svelte";
  import { formatCostEur, formatTokens } from "@/lib/utils/money";
  import type {
    AssistantEntrySummary,
    LoreEntrySummary,
    MetadataSchema,
    PromptEntrySummary,
    PromptInputDefinition,
    StructureDocument,
  } from "@/lib/types";

  export let entry: PromptEntrySummary;
  export let description: string = "";
  export let declaredInputs: PromptInputDefinition[] = [];
  export let drafts: Record<string, string> = {};
  export let assistantId: string = "";
  export let defaultAssistantLabel: string = "use machine default";
  export let assistantEntries: AssistantEntrySummary[] = [];
  export let error: string | null = null;
  export let estimate: InputsDialogEstimate | null = null;

  // Pass-throughs for PromptInputField
  export let structure: StructureDocument | null = null;
  // Research tree (sibling to manuscript) — threaded to the picker.
  export let researchStructure: StructureDocument | null = null;
  export let loreEntries: LoreEntrySummary[] = [];
  export let promptEntries: PromptEntrySummary[] = [];
  export let excludeId: string | null = null;
  export let implicitContextMatcher: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null = null;

  const dispatch = createEventDispatcher<{
    updateDraft: { name: string; value: string };
    updateAssistant: { assistantId: string };
    cancel: void;
    submit: void;
  }>();

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      dispatch("cancel");
    } else if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      dispatch("submit");
    }
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="inputs-dialog-backdrop" role="presentation" on:mousedown|self={() => dispatch("cancel")}>
  <div
    class="inputs-dialog"
    role="dialog"
    aria-label={`Run ${entry.title}`}
    aria-modal="true"
    tabindex="-1"
    on:keydown={handleKeydown}
  >
    <header>
      <strong>{entry.title}</strong>
      <small>{description}</small>
    </header>
    {#if error}
      <div class="inputs-dialog-error" role="alert">{error}</div>
    {/if}
    <div class="inputs-dialog-fields">
      {#each declaredInputs as input (input.name)}
        <label>
          {input.label || input.name}{#if input.required}<span class="required-marker"> *</span>{/if}
          <PromptInputField
            input={input}
            value={drafts[input.name] ?? ""}
            excludeId={excludeId}
            ariaLabel={input.label || input.name}
            structure={structure}
            researchStructure={researchStructure}
            loreEntries={loreEntries}
            promptEntries={promptEntries}
            implicitContextMatcher={implicitContextMatcher}
            on:change={(event) => dispatch("updateDraft", { name: input.name, value: event.detail.value })}
          />
        </label>
      {/each}
      <label>
        Assistant
        <select
          value={assistantId}
          on:change={(event) => dispatch("updateAssistant", { assistantId: event.currentTarget.value })}
        >
          <option value="">Default ({defaultAssistantLabel})</option>
          {#each assistantEntries as assistant (assistant.id)}
            <option value={assistant.id}>{assistant.title}</option>
          {/each}
        </select>
      </label>
    </div>
    {#if estimate}
      <div class="chat-estimate-strip" title="Estimated input cost for this continuation. Output cost depends on the response.">
        <span class="chat-estimate-tokens">{formatTokens(estimate.tokens)} tok</span>
        {#if estimate.cost_usd != null}
          <span class="chat-estimate-sep">·</span>
          <span class="chat-estimate-cost">{formatCostEur(estimate.cost_usd)}</span>
        {/if}
        {#if estimate.caching_style === "explicit" && estimate.cache_blocks.length > 1}
          <span class="chat-estimate-sep">·</span>
          {#each estimate.cache_blocks as block, i}
            <span class="chat-estimate-chip">{block.label} {formatTokens(block.tokens)}</span>
            {#if i < estimate.cache_blocks.length - 1}<span class="chat-estimate-sep">·</span>{/if}
          {/each}
        {/if}
      </div>
    {/if}
    <div class="inputs-dialog-actions">
      <button type="button" on:click={() => dispatch("cancel")}>Cancel</button>
      <button type="button" class="primary" on:click={() => dispatch("submit")}>Run</button>
    </div>
    <small class="inputs-dialog-hint">Ctrl/⌘+Enter to run · Esc to cancel</small>
  </div>
</div>

<style>
  .inputs-dialog-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(15, 23, 32, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .inputs-dialog {
    background: var(--surface);
    border-radius: 8px;
    box-shadow: 0 12px 36px rgba(15, 23, 32, 0.25);
    padding: 16px 20px;
    min-width: 360px;
    max-width: 520px;
    display: grid;
    gap: 12px;
  }

  .inputs-dialog-error {
    background: var(--danger-soft);
    border: 1px solid var(--danger-border);
    color: var(--danger);
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 12px;
  }

  .inputs-dialog header {
    display: grid;
    gap: 2px;
  }

  .inputs-dialog header strong {
    font-size: 15px;
  }

  .inputs-dialog header small {
    color: var(--text-2);
  }

  .inputs-dialog-fields {
    display: grid;
    gap: 10px;
  }

  .inputs-dialog-fields label {
    display: grid;
    gap: 4px;
    font-size: 13px;
  }

  .inputs-dialog-fields .required-marker {
    color: var(--danger);
  }

  /* Form controls inside the fields are rendered by the child
     PromptInputField (plus the own Assistant <select>), so the element
     targets need :global to reach across the component boundary. */
  .inputs-dialog-fields :global(textarea),
  .inputs-dialog-fields :global(input[type="text"]),
  .inputs-dialog-fields :global(input[type="number"]),
  .inputs-dialog-fields :global(select) {
    width: 100%;
    box-sizing: border-box;
  }

  .inputs-dialog-fields :global(textarea) {
    font-family: inherit;
    resize: vertical;
  }

  .inputs-dialog-actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
  }

  .inputs-dialog-actions .primary {
    background: var(--accent);
    color: var(--surface);
    border-color: var(--accent);
  }

  .inputs-dialog-actions .primary:hover {
    background: var(--accent-strong);
    border-color: var(--accent-strong);
  }

  .inputs-dialog-hint {
    color: var(--text-3);
    font-size: 11px;
    text-align: right;
  }

  /* V2: pre-send token + cost strip above the chat composer. Compact
     horizontal line — no card, reads as metadata rather than a UI element. */
  .chat-estimate-strip {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    padding: 4px 8px 2px;
    font-size: 0.78em;
    color: var(--color-muted, #888);
    cursor: default;
  }

  .chat-estimate-tokens,
  .chat-estimate-cost {
    font-variant-numeric: tabular-nums;
  }

  .chat-estimate-cost {
    color: var(--color-text, #ccc);
  }

  .chat-estimate-sep {
    opacity: 0.6;
  }

  .chat-estimate-chip {
    font-variant-numeric: tabular-nums;
    opacity: 0.85;
  }
</style>
