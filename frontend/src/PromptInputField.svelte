<script lang="ts">
  // Shared input control for a PromptInputDefinition. Renders the
  // type-specific element (text / long_text / number / boolean / select /
  // entity_ref / entity_ref_list) and emits a `change` event with the new
  // value as a string. Used by both the inputs-dialog (prompt-dispatch flow)
  // and the prompt-preview inputs panel — keeps look-and-feel identical and
  // halves the maintenance surface for input types.
  import { createEventDispatcher } from "svelte";
  import NodePicker from "./NodePicker.svelte";
  import PlainTextEditor from "./PlainTextEditor.svelte";
  import ReferencePicker from "./ReferencePicker.svelte";
  import type {
    NodePickerConfig,
    NodePickerRef,
    LoreEntrySummary,
    MetadataFieldDefinition,
    PromptEntrySummary,
    PromptInputDefinition,
    StructureDocument,
  } from "./types";

  export let input: PromptInputDefinition;
  export let value: string;
  export let excludeId: string | null = null;
  export let ariaLabel: string | undefined = undefined;
  // Data sources for the context_pick input type. Optional — the picker
  // will degrade to "no items" when missing rather than throw.
  export let structure: StructureDocument | null = null;
  // Research tree (sibling to manuscript) — threaded to the picker.
  export let researchStructure: StructureDocument | null = null;
  export let loreEntries: LoreEntrySummary[] = [];
  export let promptEntries: PromptEntrySummary[] = [];
  // Optional matcher pass-through for implicit-context highlighting on
  // long_text inputs. Other input types ignore it.
  export let implicitContextMatcher: import("./implicitContextMatcher").CompiledMatcher | null = null;

  const dispatch = createEventDispatcher<{ change: { value: string } }>();

  function refStubField(): MetadataFieldDefinition {
    // entity_ref / entity_ref_list inputs persist their picker config as a
    // NodePickerConfig under `target` (post-#40). ReferencePicker reads it
    // via `picker_config`, the same shape used on the field side.
    const picker =
      input.target && typeof input.target === "object"
        ? (input.target as unknown as NodePickerConfig)
        : null;
    return {
      name: input.label || input.name,
      type: input.type === "entity_ref_list" ? "entity_ref_list" : "entity_ref",
      options: [],
      picker_config: picker,
    };
  }

  function decodeRefValue(raw: string): string | string[] {
    if (input.type === "entity_ref_list") {
      try {
        const parsed = JSON.parse(raw || "[]");
        return Array.isArray(parsed) ? parsed.map(String) : [];
      } catch {
        return [];
      }
    }
    return raw || "";
  }

  function encodeRefValue(v: string | string[]): string {
    return Array.isArray(v) ? JSON.stringify(v) : (v ?? "");
  }

  function decodeContextPickValue(raw: string): NodePickerRef[] {
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(
        (item): item is NodePickerRef =>
          item && typeof item === "object" && typeof item.id === "string" && typeof item.kind === "string",
      );
    } catch {
      return [];
    }
  }
</script>

{#if input.type === "long_text"}
  <PlainTextEditor
    value={value ?? ""}
    ariaLabel={ariaLabel ?? (input.label || input.name)}
    minHeight={60}
    maxHeight={200}
    matcher={implicitContextMatcher}
    on:change={(e) => dispatch("change", { value: e.detail.value })}
  />
{:else if input.type === "number"}
  <input
    type="number"
    value={value ?? ""}
    aria-label={ariaLabel}
    on:input={(e) => dispatch("change", { value: (e.currentTarget as HTMLInputElement).value })}
  />
{:else if input.type === "boolean"}
  <!-- Tri-state: Unset / True / False. Unset is a real persisted state
       (#24, #42) — preview and runtime both treat it as undefined so the
       template can guard with `is defined` and fail fast otherwise.
       Replaces the 2-state checkbox that silently coerced "untouched"
       into `false` and disagreed with the preview. -->
  <select
    value={value ?? ""}
    aria-label={ariaLabel}
    on:change={(e) => dispatch("change", { value: (e.currentTarget as HTMLSelectElement).value })}
  >
    <option value="">Unset</option>
    <option value="true">True</option>
    <option value="false">False</option>
  </select>
{:else if input.type === "select"}
  <select
    value={value ?? ""}
    aria-label={ariaLabel}
    on:change={(e) => dispatch("change", { value: (e.currentTarget as HTMLSelectElement).value })}
  >
    {#if !input.required}
      <option value="">(none)</option>
    {/if}
    {#each input.options ?? [] as option}
      <option value={option.value}>{option.label ?? option.value}</option>
    {/each}
  </select>
{:else if input.type === "entity_ref" || input.type === "entity_ref_list"}
  <ReferencePicker
    field={refStubField()}
    value={decodeRefValue(value)}
    excludeId={excludeId}
    ariaLabel={ariaLabel ?? (input.label || input.name)}
    structure={structure}
    researchStructure={researchStructure}
    loreEntries={loreEntries}
    promptEntries={promptEntries}
    on:change={(event) => dispatch("change", { value: encodeRefValue(event.detail.value) })}
  />
{:else if input.type === "context_pick"}
  <NodePicker
    config={(input.target ?? {}) as NodePickerConfig}
    value={decodeContextPickValue(value)}
    label={input.label || input.name || "Context"}
    structure={structure}
    researchStructure={researchStructure}
    loreEntries={loreEntries}
    promptEntries={promptEntries}
    on:change={(event) => dispatch("change", { value: JSON.stringify(event.detail.value) })}
  />
{:else}
  <input
    type="text"
    value={value ?? ""}
    aria-label={ariaLabel}
    on:input={(e) => dispatch("change", { value: (e.currentTarget as HTMLInputElement).value })}
  />
{/if}
