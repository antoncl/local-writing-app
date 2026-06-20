<script lang="ts">
  // Shared input control for a PromptInputDefinition. Renders the
  // type-specific element (text / long_text / number / boolean / select /
  // entity_ref / entity_ref_list) and emits a `change` event with the new
  // value as a string. Used by both the inputs-dialog (prompt-dispatch flow)
  // and the prompt-preview inputs panel — keeps look-and-feel identical and
  // halves the maintenance surface for input types.
  import { createEventDispatcher } from "svelte";
  import ReferencePicker from "./ReferencePicker.svelte";
  import type { MetadataSchema, PromptInputDefinition } from "./types";

  export let input: PromptInputDefinition;
  export let value: string;
  export let metadataSchema: MetadataSchema | null = null;
  export let excludeId: string | null = null;
  export let ariaLabel: string | undefined = undefined;

  const dispatch = createEventDispatcher<{ change: { value: string } }>();

  function refStubField() {
    const target: Record<string, string> = {};
    const t = input.target as { kind?: unknown; entry_type?: unknown } | null | undefined;
    if (t && typeof t.kind === "string") target.kind = t.kind;
    if (t && typeof t.entry_type === "string") target.entry_type = t.entry_type;
    return {
      name: input.label || input.name,
      type: input.type === "entity_ref_list" ? "entity_ref_list" : "entity_ref",
      options: [] as string[],
      target: Object.keys(target).length ? target : null,
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
</script>

{#if input.type === "long_text"}
  <textarea
    rows="3"
    value={value ?? ""}
    aria-label={ariaLabel}
    on:input={(e) => dispatch("change", { value: (e.currentTarget as HTMLTextAreaElement).value })}
  ></textarea>
{:else if input.type === "number"}
  <input
    type="number"
    value={value ?? ""}
    aria-label={ariaLabel}
    on:input={(e) => dispatch("change", { value: (e.currentTarget as HTMLInputElement).value })}
  />
{:else if input.type === "boolean"}
  <input
    type="checkbox"
    checked={value === "true"}
    aria-label={ariaLabel}
    on:change={(e) => dispatch("change", { value: (e.currentTarget as HTMLInputElement).checked ? "true" : "false" })}
  />
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
      <option value={option}>{option}</option>
    {/each}
  </select>
{:else if input.type === "entity_ref" || input.type === "entity_ref_list"}
  <ReferencePicker
    field={refStubField()}
    value={decodeRefValue(value)}
    metadataSchema={metadataSchema}
    excludeId={excludeId}
    ariaLabel={ariaLabel ?? (input.label || input.name)}
    on:change={(event) => dispatch("change", { value: encodeRefValue(event.detail.value) })}
  />
{:else}
  <input
    type="text"
    value={value ?? ""}
    aria-label={ariaLabel}
    on:input={(e) => dispatch("change", { value: (e.currentTarget as HTMLInputElement).value })}
  />
{/if}
