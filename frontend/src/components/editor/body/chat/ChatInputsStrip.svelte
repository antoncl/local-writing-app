<!--
  ChatInputsStrip — declared-inputs strip for ChatBodyView (#99).
  Renders a PromptInputField per declared prompt input. Presentational:
  the parent still owns chatInputDrafts + persistence; edits flow back via
  onDraftChange.

  ADR-0076 S2: pre-lock only now — a locked chat's filled values render
  read-only in the Context door's "Inputs (locked)" section instead (the
  post-lock "Show inputs" collapse retired). So this strip is a pure form:
  no locked/disabled branches, no collapse toggle.
-->
<script lang="ts">
  import PromptInputField from "@/components/widgets/PromptInputField.svelte";
  import { isInputMissing } from "@/lib/utils/promptInputs";
  import type {
    LoreEntrySummary,
    PromptEntrySummary,
    PromptInputDefinition,
    StructureDocument,
  } from "@/lib/types";

  interface Props {
    declaredInputs: PromptInputDefinition[];
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
    chatInputDrafts,
    structure,
    researchStructure,
    loreEntries,
    promptEntries,
    implicitContextMatcher,
    onDraftChange,
  }: Props = $props();

  // A launch-set input (ADR-0046 §6.4) is declared so it reaches the template,
  // but not authored here — skip its widget. If every input is hidden, the
  // strip renders nothing.
  let visibleInputs = $derived(declaredInputs.filter((i) => !i.hidden));
</script>

<div class="cbv-inputs-strip">
  {#if visibleInputs.length > 0}
    <div class="cbv-inputs-fields">
      {#each visibleInputs as input (input.name)}
        {@const missing = input.required && isInputMissing(input, chatInputDrafts[input.name])}
        <label class="cbv-input-field" class:cbv-input-missing={missing}>
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
            onChange={(next) => onDraftChange(input.name, next)}
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
  .cbv-inputs-fields { display: flex; flex-direction: column; gap: 8px; }
  .cbv-input-field { display: flex; flex-direction: column; gap: 3px; font-size: var(--fs-sm); }
  .cbv-input-label {
    font-size: var(--fs-xs); font-weight: 600; letter-spacing: 0.07em; text-transform: uppercase; color: var(--text-3);
  }
  .cbv-required-marker { color: var(--danger); }
  .cbv-input-field.cbv-input-missing > .cbv-input-label { color: var(--danger); }
</style>
