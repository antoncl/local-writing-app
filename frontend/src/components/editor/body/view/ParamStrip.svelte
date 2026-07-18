<script lang="ts">
  // The runtime parameter strip (ADR-0032 §D): one editable control per declared
  // formal, seeded by its authored default and overridable. The SINGLE strip
  // implementation (#275): both the designer preview (ViewBodyView) and the panes
  // (via ViewNodeList) render this component, so the control logic lives once.
  // Renders nothing when the spec declares no parameters.
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import { effectiveParamValue, resolveParamControls } from "@/lib/views/viewParams";
  import { loreEntriesStore } from "@/lib/stores/lore";
  import { promptEntriesStore } from "@/lib/stores/prompts";
  import { structureStore, researchStructureStore } from "@/lib/stores/structure";
  import { knownTagsStore } from "@/lib/stores/tags";
  import type { DocumentKind, MetadataSchema, MetadataValue, ViewSpec } from "@/lib/types";

  let {
    spec,
    schema = null,
    overrides = $bindable<Record<string, unknown>>({}),
  }: { spec: ViewSpec; schema?: MetadataSchema | null; overrides?: Record<string, unknown> } = $props();

  const controls = $derived(resolveParamControls(spec, schema));

  function displayValue(name: string): MetadataValue {
    if (name in overrides) return overrides[name] as MetadataValue;
    return (spec.params?.find((p) => p.name === name)?.default ?? null) as MetadataValue;
  }
  function setParam(name: string, value: MetadataValue): void {
    overrides = { ...overrides, [name]: value };
  }
  function clearParam(name: string): void {
    const { [name]: _dropped, ...rest } = overrides;
    overrides = rest;
  }
  function active(name: string): boolean {
    const p = spec.params?.find((param) => param.name === name);
    return p ? effectiveParamValue(p, overrides).length > 0 : false;
  }
</script>

{#if controls.length > 0}
  <div class="param-strip" role="group" aria-label="View parameters">
    {#each controls as control (control.name)}
      <div class="param" class:active={active(control.name)}>
        <span class="param-label">{control.label}</span>
        <div class="param-control">
          <FieldValueEditor
            field={control.field}
            value={displayValue(control.name)}
            onChange={(v) => setParam(control.name, v)}
            ariaLabel={control.label}
            loreEntries={$loreEntriesStore}
            promptEntries={$promptEntriesStore}
            structure={$structureStore}
            researchStructure={$researchStructureStore}
            knownTags={$knownTagsStore}
            documentKind={spec.kind as DocumentKind}
          />
          {#if control.name in overrides}
            <button class="param-clear" title="Reset to default" aria-label={`Reset ${control.label} to default`} onclick={() => clearParam(control.name)}>↺</button>
          {/if}
        </div>
      </div>
    {/each}
  </div>
{/if}

<style>
  .param-strip {
    display: flex;
    flex-direction: column;
    gap: var(--sp-2);
    padding: var(--sp-2);
  }
  .param {
    display: flex;
    flex-direction: column;
    gap: var(--sp-1);
  }
  .param-label {
    font-size: var(--fs-xs);
    color: var(--text-2);
  }
  .param.active .param-label {
    color: var(--text);
  }
  .param-control {
    display: flex;
    align-items: center;
    gap: var(--sp-1);
  }
  .param-control :global(> :first-child) {
    flex: 1 1 auto;
    min-width: 0;
  }
  .param-clear {
    flex: 0 0 auto;
    border: none;
    background: none;
    cursor: pointer;
    color: var(--text-3);
    font-size: var(--fs-sm);
    line-height: 1;
  }
  .param-clear:hover {
    color: var(--text);
  }
</style>
