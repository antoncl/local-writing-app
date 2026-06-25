<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import PromptInputField from "./PromptInputField.svelte";
  import { formatCostEur, formatTokens } from "./money";
  import type {
    AssistantEntrySummary,
    LoreEntrySummary,
    MetadataSchema,
    PromptEntrySummary,
    PromptInputDefinition,
    StructureDocument,
  } from "./types";

  export type InputsDialogEstimate = {
    tokens: number;
    cost_usd: number | null;
    caching_style: "none" | "auto" | "explicit" | null;
    cache_blocks: { label: string; tokens: number; cache_break_after: boolean }[];
  };

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
  export let metadataSchema: MetadataSchema | null = null;
  export let structure: StructureDocument | null = null;
  export let loreEntries: LoreEntrySummary[] = [];
  export let promptEntries: PromptEntrySummary[] = [];
  export let excludeId: string | null = null;
  export let implicitContextMatcher: import("./implicitContextMatcher").CompiledMatcher | null = null;

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
            metadataSchema={metadataSchema}
            excludeId={excludeId}
            ariaLabel={input.label || input.name}
            structure={structure}
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
