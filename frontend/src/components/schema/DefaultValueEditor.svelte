<script lang="ts">
  // Type-aware default-value editor shared between prompt-input definitions
  // and metadata-field definitions. Per decisions-inputs-fields-uniformity:
  // same widget per type, across all surfaces that author a default value.
  //
  // Wire contract: an empty string from any control means "unset" — the
  // change event surfaces `undefined`, so the caller can persist a real
  // absence rather than coercing it into a falsy value (#24).
  //
  // Storage shape stays editor-side strings; the host (NodeEditor's
  // defaultValueForStorage, App.svelte's schemaFieldDefaultForStorage) is
  // responsible for type-matched serialization (boolean → bool, number →
  // number, etc.). This component is intentionally string-typed so it
  // can be embedded inside <label> rows and forms without coupling to
  // the persistence layer.

  import type { OptionDraft } from "@/components/schema/SelectOptionsEditor.svelte";

  interface Props {
    type: string;
    value: string | undefined;
    // SelectOption-shaped draft list; used to populate the dropdown for
    // select / multi_select. Ignored for other types.
    options?: OptionDraft[];
    ariaLabel?: string;
    // Emitted on edit; "" means unset → surfaced as undefined (#24). (#14 runes:
    // callback prop replaces the old `change` event dispatcher.)
    onChange?: (value: string | undefined) => void;
  }

  let { type, value, options = [], ariaLabel = "Default value", onChange = () => {} }: Props = $props();

  function emit(raw: string) {
    onChange(raw === "" ? undefined : raw);
  }
</script>

{#if type === "boolean"}
  <!-- 3-state: Unset (no default) / True / False. Unset is a real
       persisted state, not a silent false (#24). -->
  <select
    value={value ?? ""}
    aria-label={ariaLabel}
    onchange={(e) => emit((e.currentTarget as HTMLSelectElement).value)}
  >
    <option value="">Unset</option>
    <option value="true">True</option>
    <option value="false">False</option>
  </select>
{:else if type === "number"}
  <!-- Wrapped so the explicit clear-to-unset button (#41) can sit
       alongside the input. Empty input still IS unset; the button just
       makes resetting from a typed value to unset obvious + cheap. -->
  <span class="dve-clearable">
    <input
      type="number"
      value={value ?? ""}
      placeholder="Unset"
      aria-label={ariaLabel}
      oninput={(e) => emit((e.currentTarget as HTMLInputElement).value)}
    />
    {#if value !== undefined && value !== ""}
      <button
        type="button"
        class="dve-clear"
        title="Clear default (unset)"
        aria-label="Clear default"
        onclick={() => emit("")}
      >×</button>
    {/if}
  </span>
{:else if type === "select" || type === "multi_select"}
  <select
    value={value ?? ""}
    aria-label={ariaLabel}
    onchange={(e) => emit((e.currentTarget as HTMLSelectElement).value)}
  >
    <option value="">Unset</option>
    {#each options.filter((o) => o.value.trim() !== "") as opt (opt.value)}
      <option value={opt.value}>{opt.label || opt.value}</option>
    {/each}
  </select>
{:else}
  <!-- text / long_text / date / color / entity_ref(_list) / tags / etc.:
       typed picker for refs is a follow-up. Empty input = Unset; the
       explicit clear button (#41) makes resetting from a typed value
       back to unset obvious + cheap. -->
  <span class="dve-clearable">
    <input
      value={value ?? ""}
      placeholder="Unset"
      aria-label={ariaLabel}
      oninput={(e) => emit((e.currentTarget as HTMLInputElement).value)}
    />
    {#if value !== undefined && value !== ""}
      <button
        type="button"
        class="dve-clear"
        title="Clear default (unset)"
        aria-label="Clear default"
        onclick={() => emit("")}
      >×</button>
    {/if}
  </span>
{/if}

<style>
  .dve-clearable {
    display: inline-flex;
    align-items: stretch;
    gap: 4px;
    width: 100%;
  }
  .dve-clearable > input {
    flex: 1;
    min-width: 0;
  }
  .dve-clear {
    flex: none;
    appearance: none;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-3);
    font-size: 14px;
    line-height: 1;
    padding: 0 7px;
    border-radius: 4px;
    cursor: pointer;
  }
  .dve-clear:hover {
    color: var(--text);
    border-color: var(--border-strong);
  }
</style>
