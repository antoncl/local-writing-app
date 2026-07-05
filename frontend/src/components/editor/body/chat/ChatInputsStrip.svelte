<!--
  ChatInputsStrip — declared-inputs strip for ChatBodyView (#99).
  Renders a PromptInputField per declared prompt input. Presentational:
  the parent still owns chatInputDrafts + persistence; edits flow back via
  onDraftChange, and the collapse toggle mutates the bound `hidden`.
-->
<script lang="ts">
  import PromptInputField from "@/components/widgets/PromptInputField.svelte";
  import { isInputMissing } from "@/components/editor/body/chat/chatInputs";
  import type {
    LoreEntrySummary,
    PromptEntrySummary,
    PromptInputDefinition,
    StructureDocument,
  } from "@/lib/types";

  interface Props {
    declaredInputs: PromptInputDefinition[];
    isLocked: boolean;
    hidden?: boolean;
    chatInputDrafts: Record<string, string>;
    structure: StructureDocument | null;
    researchStructure: StructureDocument | null;
    loreEntries: LoreEntrySummary[];
    promptEntries: PromptEntrySummary[];
    implicitContextMatcher: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    onDraftChange: (name: string, value: string) => void;
  }

  let {
    declaredInputs,
    isLocked,
    hidden = $bindable(false),
    chatInputDrafts,
    structure,
    researchStructure,
    loreEntries,
    promptEntries,
    implicitContextMatcher,
    onDraftChange,
  }: Props = $props();
</script>

<div class="cbv-inputs-strip" class:cbv-inputs-locked={isLocked}>
  {#if isLocked}
    <button
      type="button"
      class="cbv-inputs-toggle"
      aria-expanded={!hidden}
      onclick={() => (hidden = !hidden)}
    >{hidden ? "▸ Show inputs" : "▾ Hide inputs"}</button>
  {/if}
  {#if !isLocked || !hidden}
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
            on:change={(event) => !isLocked && onDraftChange(input.name, event.detail.value)}
          />
        </label>
      {/each}
    </div>
  {/if}
</div>

<style>
  /* ---- 5 · inputs strip (inset) ---- */
  /* flex: 0 0 auto keeps the strip at natural height as a flex child of
     .chat-body-view (was carried by the shared sibling-group rule in the
     parent before this block moved out — #99). */
  .cbv-inputs-strip {
    flex: 0 0 auto;
    display: flex; flex-direction: column; gap: 8px; padding: 11px 14px;
    border-radius: 10px; border: 1px solid var(--divider); background: var(--inset);
  }
  .cbv-inputs-toggle {
    align-self: flex-start; padding: 2px 6px; font-size: var(--fs-xs); font-weight: 600;
    background: transparent; border: none; cursor: pointer; color: var(--text-3);
  }
  .cbv-inputs-fields { display: flex; flex-direction: column; gap: 8px; }
  .cbv-input-field { display: flex; flex-direction: column; gap: 3px; font-size: var(--fs-sm); }
  .cbv-input-label {
    font-size: var(--fs-xs); font-weight: 800; letter-spacing: 0.07em; text-transform: uppercase; color: var(--text-3);
  }
  .cbv-required-marker { color: var(--danger); }
  .cbv-input-field.cbv-input-missing > .cbv-input-label { color: var(--danger); }
  .cbv-input-field.cbv-input-disabled { opacity: 0.7; }
</style>
