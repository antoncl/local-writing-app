<script lang="ts">
  // The "Your subscriptions" provider surface (ADR-0047 slice 2). Presents the
  // configured cloud providers as chips + a "+ Add provider" form, over the flat
  // machine-config credential fields — the extensible model the create wizard
  // uses. A **controlled** component: the host supplies the current credentials
  // and the persistence callback, so the same surface serves the wizard
  // (immediate per-key writes) and the Settings dialog (edits a draft, saved in
  // one batch). Provider identity/derivation lives in the shared, unit-tested
  // `aiProviders.ts`, so a new provider is one entry there, not new markup here.
  //
  // `editable` adds rotate/remove affordances the Settings tab needs (change a
  // key, drop a subscription) and the wizard's set-up-once flow does not.
  import type { ProviderCredentialsView } from "@/lib/types";
  import {
    addableCloudProviders,
    cloudKeyField,
    cloudKeyPlaceholder,
    configuredCloudProviders,
    PROVIDER_DISPLAY_NAMES,
  } from "@/lib/utils/aiProviders";

  export let providers: ProviderCredentialsView;
  // The machine default provider, highlighted as the live one. Display only.
  export let defaultProviderId: string = "";
  // Settings passes true (rotate/remove); the wizard leaves it false (add-only).
  export let editable: boolean = false;
  // True while a write is in flight — disables the form's commit (wizard).
  export let busy: boolean = false;
  export let onSaveKey: (
    field: keyof ProviderCredentialsView,
    value: string,
  ) => void | Promise<void>;
  // Only used when `editable`; clears a provider's key (drops the subscription).
  export let onClearKey: ((field: keyof ProviderCredentialsView) => void) | undefined = undefined;

  $: configured = configuredCloudProviders(providers);
  $: addable = addableCloudProviders(providers);

  // Add/rotate form. "add" shows the addable <select>; "rotate" targets one
  // already-configured provider (a label, no select).
  let formMode: "none" | "add" | "rotate" = "none";
  let formProviderId = "";
  let formSecret = "";

  function resetForm() {
    formMode = "none";
    formProviderId = "";
    formSecret = "";
  }

  function beginAdd() {
    if (addable.length === 0) return;
    formMode = "add";
    formProviderId = addable[0].id;
    formSecret = "";
  }

  function beginRotate(id: string) {
    formMode = "rotate";
    formProviderId = id;
    formSecret = "";
  }

  async function commit() {
    const field = cloudKeyField(formProviderId);
    const value = formSecret.trim();
    if (!field || !value) return;
    await onSaveKey(field, value);
    resetForm();
  }

  function remove(id: string) {
    const field = cloudKeyField(id);
    if (field && onClearKey) onClearKey(field);
  }
</script>

<div class="provider-subs">
  {#if configured.length > 0}
    <div class="chip-tags">
      {#each configured as prov (prov.id)}
        <span class="chip-tag" class:is-active={prov.id === defaultProviderId}>
          <span class="chip-tag-label">{prov.label}</span>
          {#if editable}
            <button
              type="button"
              class="chip-tag-btn"
              title={`Change ${prov.label} key`}
              aria-label={`Change ${prov.label} key`}
              disabled={busy}
              on:click={() => beginRotate(prov.id)}
            ><i class="ti ti-pencil" aria-hidden="true"></i></button>
            <button
              type="button"
              class="chip-tag-btn is-remove"
              title={`Remove ${prov.label}`}
              aria-label={`Remove ${prov.label}`}
              disabled={busy}
              on:click={() => remove(prov.id)}
            ><i class="ti ti-x" aria-hidden="true"></i></button>
          {/if}
        </span>
      {/each}
    </div>
  {:else}
    <p class="muted">No cloud provider configured yet — add one to use cloud AI.</p>
  {/if}

  {#if formMode !== "none"}
    <div class="inline-form">
      {#if formMode === "add"}
        <label>
          Provider
          <select bind:value={formProviderId}>
            {#each addable as prov (prov.id)}
              <option value={prov.id}>{prov.label}</option>
            {/each}
          </select>
        </label>
      {:else}
        <div class="rotate-target">
          Change key — <strong>{PROVIDER_DISPLAY_NAMES[formProviderId] ?? formProviderId}</strong>
        </div>
      {/if}
      <label>
        API key
        <input
          type="password"
          autocomplete="off"
          bind:value={formSecret}
          placeholder={cloudKeyPlaceholder(formProviderId)}
        />
      </label>
      <div class="inline-form-actions">
        <button type="button" on:click={resetForm}>Cancel</button>
        <button
          type="button"
          class="primary"
          disabled={busy || !formSecret.trim()}
          on:click={commit}>Save</button
        >
      </div>
    </div>
  {:else if addable.length > 0}
    <button type="button" class="inline-add-btn" on:click={beginAdd}>+ Add provider</button>
  {/if}
</div>

<style>
  /* Chips + inline form use the shared .chip-tag* / .inline-form* primitives
     in styles.css (#619). Only the rotate-mode label is specific here. */
  .provider-subs {
    display: grid;
    gap: 10px;
  }

  .rotate-target {
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
</style>
