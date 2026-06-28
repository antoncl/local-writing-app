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

  import { createEventDispatcher } from "svelte";
  import type { OptionDraft } from "./SelectOptionsEditor.svelte";

  export let type: string;
  export let value: string | undefined;
  // SelectOption-shaped draft list; used to populate the dropdown for
  // select / multi_select. Ignored for other types.
  export let options: OptionDraft[] = [];
  export let ariaLabel: string = "Default value";

  const dispatch = createEventDispatcher<{ change: { value: string | undefined } }>();

  function emit(raw: string) {
    dispatch("change", { value: raw === "" ? undefined : raw });
  }
</script>

{#if type === "boolean"}
  <!-- 3-state: Unset (no default) / True / False. Unset is a real
       persisted state, not a silent false (#24). -->
  <select
    value={value ?? ""}
    aria-label={ariaLabel}
    on:change={(e) => emit((e.currentTarget as HTMLSelectElement).value)}
  >
    <option value="">Unset</option>
    <option value="true">True</option>
    <option value="false">False</option>
  </select>
{:else if type === "number"}
  <input
    type="number"
    value={value ?? ""}
    placeholder="Unset"
    aria-label={ariaLabel}
    on:input={(e) => emit((e.currentTarget as HTMLInputElement).value)}
  />
{:else if type === "select" || type === "multi_select"}
  <select
    value={value ?? ""}
    aria-label={ariaLabel}
    on:change={(e) => emit((e.currentTarget as HTMLSelectElement).value)}
  >
    <option value="">Unset</option>
    {#each options.filter((o) => o.value.trim() !== "") as opt (opt.value)}
      <option value={opt.value}>{opt.label || opt.value}</option>
    {/each}
  </select>
{:else}
  <!-- text / long_text / date / color / entity_ref(_list) / tags / etc.:
       typed picker for refs is a follow-up (#41 covers an explicit unset
       affordance for text/number); empty = Unset. -->
  <input
    value={value ?? ""}
    placeholder="Unset"
    aria-label={ariaLabel}
    on:input={(e) => emit((e.currentTarget as HTMLInputElement).value)}
  />
{/if}
