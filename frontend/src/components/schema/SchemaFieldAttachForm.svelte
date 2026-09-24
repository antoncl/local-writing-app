<script lang="ts">
  // "+ Existing field" form (#2180) — mirrors SchemaTypeEditor's group-apply
  // form (`.group-apply-form`, same `.sfi-field`/`.sfi-footer` atoms): pick an
  // already-defined field id and attach it to the open type's membership
  // WITHOUT creating a new shared definition. A small standalone component so
  // SchemaTypeEditor (already ~1040 lines) doesn't grow the inline markup.
  import { untrack } from "svelte";
  import type { MetadataFieldDefinition } from "@/lib/types";

  interface Props {
    // The attachable candidates (`attachableFields`), sorted by display name.
    fields: [string, MetadataFieldDefinition][];
    onAttach?: (fieldId: string) => void | Promise<boolean | void>;
    onCancel?: () => void;
  }

  let { fields, onAttach = () => {}, onCancel = () => {} }: Props = $props();

  // Seeded once at mount, like SchemaTypeEditor's group-apply form.
  let selectedFieldId = $state(untrack(() => fields[0]?.[0] ?? ""));

  async function submit() {
    if (!selectedFieldId) return;
    const result = await onAttach(selectedFieldId);
    if (result !== false) onCancel();
  }
</script>

<div class="field-attach-form" data-testid="schema-field-attach-form">
  <label class="sfi-field">
    Field
    <select bind:value={selectedFieldId} data-testid="schema-field-attach-select">
      {#each fields as [fieldId, field] (fieldId)}
        <option value={fieldId}>{field.name} ({fieldId})</option>
      {/each}
    </select>
  </label>
  <div class="sfi-footer">
    <span class="sfi-spacer"></span>
    <button class="sfi-cancel" type="button" onclick={() => onCancel()} data-testid="schema-field-attach-cancel">
      Cancel
    </button>
    <button
      class="sfi-done"
      type="button"
      disabled={!selectedFieldId}
      onclick={submit}
      data-testid="schema-field-attach-add"
    >
      Add
    </button>
  </div>
</div>

<style>
  .field-attach-form {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 10px;
    padding: 10px;
    border: 1px solid var(--divider);
    border-radius: 8px;
    background: var(--inset);
    box-shadow: inset 3px 0 0 0 var(--accent);
  }
  .field-attach-form .sfi-field {
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
  }
  .field-attach-form .sfi-footer {
    flex-basis: 100%;
  }
</style>
