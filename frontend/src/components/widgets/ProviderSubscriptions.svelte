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
    <div class="provider-chips">
      {#each configured as prov (prov.id)}
        <span class="provider-chip" class:is-default={prov.id === defaultProviderId}>
          <span class="chip-label">{prov.label}</span>
          {#if editable}
            <button
              type="button"
              class="chip-action"
              title={`Change ${prov.label} key`}
              aria-label={`Change ${prov.label} key`}
              disabled={busy}
              on:click={() => beginRotate(prov.id)}
            ><i class="ti ti-pencil" aria-hidden="true"></i></button>
            <button
              type="button"
              class="chip-action chip-remove"
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
    <div class="ai-add">
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
      <div class="ai-actions">
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
    <button type="button" class="ai-linkbtn" on:click={beginAdd}>+ Add provider</button>
  {/if}
</div>

<style>
  .provider-subs {
    display: grid;
    gap: 10px;
  }

  .provider-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  /* A chip is a pill; in editable mode it holds a label-button + a remove ×. */
  .provider-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px 2px 10px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--surface);
    color: var(--text-2);
    font-size: var(--fs-sm);
  }

  /* The machine default provider reads as the live one. */
  .provider-chip.is-default {
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--accent-emphasis);
    font-weight: 600;
  }

  .chip-label {
    padding: 0 2px;
  }

  /* Explicit per-chip affordances: a pencil (rotate the key) and an × (remove),
     each with its own aria-label — the provider name is plain text, so the
     actions are visible controls, not a hidden "click the label" gesture. */
  .chip-action {
    display: inline-flex;
    align-items: center;
    appearance: none;
    background: transparent;
    border: none;
    padding: 0 2px;
    color: var(--text-3);
    font-size: var(--fs-md);
    line-height: 1;
    cursor: pointer;
  }

  .chip-action:hover:not(:disabled) {
    color: var(--text);
  }

  .chip-remove:hover:not(:disabled) {
    color: var(--danger);
  }

  .chip-action:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  /* Inline add/rotate draft — mirrors the wizard's .ai-add treatment. */
  .ai-add {
    display: grid;
    gap: 8px;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel);
  }

  .rotate-target {
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  .ai-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }

  /* Dashed link-style action, matching the wizard's "+ Add provider". */
  .ai-linkbtn {
    justify-self: start;
    border: 1px dashed var(--border-strong);
    background: transparent;
    color: var(--accent-emphasis);
    font-size: var(--fs-sm);
    padding: 4px 12px;
    border-radius: 6px;
    cursor: pointer;
  }

  .ai-linkbtn:hover {
    background: var(--surface);
  }
</style>
