<script lang="ts">
  // The "Your providers" surface (ADR-0047 slice 2; generalized in #1417).
  // Presents every provider in scope as a chip + a "+ Add provider" form, over
  // the flat machine-config credential fields — the extensible model the create
  // wizard and the Settings AI tab both use. A **controlled** component: the host
  // supplies the current credentials and the persistence callback, so the same
  // surface serves the wizard (immediate per-key writes) and Settings (edits a
  // draft, saved in one batch).
  //
  // No provider is special-cased. Each is a `ProviderDescriptor` (aiProviders.ts)
  // that declares its config options: a `secret` credential is a masked API key;
  // a `url` credential (Ollama's host) is a plain text field, always "configured",
  // and — because its descriptor says so — carries a reachability Test. So Ollama
  // is just another provider whose config options differ; moving the policy slider
  // up only widens `allowed`, showing more providers here.
  import type { OllamaHostHealth, ProviderCredentialsView } from "@/lib/types";
  import {
    addableProviders,
    configuredProviders,
    providerDescriptor,
    providerField,
    providerPlaceholder,
    type ProviderDescriptor,
  } from "@/lib/utils/aiProviders";

  let {
    providers,
    // The provider ids this surface may show (wizard: policy-derived; Settings:
    // omitted = all supported). Widens as the policy slider moves up.
    allowed = undefined,
    // The machine default provider, highlighted as the live one. Display only.
    defaultProviderId = "",
    // Settings passes true (rotate a secret / drop a subscription). A `url`
    // provider is always editable regardless — you must be able to change its
    // host — and is never removable.
    editable = false,
    // True while a write is in flight — disables the form's commit (wizard).
    busy = false,
    onSaveKey,
    // Only used for a removable (secret) provider; clears its key.
    onClearKey = undefined,
    // Reachability probe for a provider whose descriptor declares one (Ollama).
    // Tests the value currently typed in the form, so a user can iterate before
    // saving. Returns the health readout; never expected to throw for "offline".
    onTestReachability = undefined,
  }: {
    providers: ProviderCredentialsView;
    allowed?: string[] | undefined;
    defaultProviderId?: string;
    editable?: boolean;
    busy?: boolean;
    onSaveKey: (field: keyof ProviderCredentialsView, value: string) => void | Promise<void>;
    onClearKey?: ((field: keyof ProviderCredentialsView) => void) | undefined;
    onTestReachability?:
      | ((providerId: string, value: string) => Promise<OllamaHostHealth>)
      | undefined;
  } = $props();

  const configured = $derived(configuredProviders(providers, allowed));
  const addable = $derived(addableProviders(providers, allowed));

  // Add/edit form. "add" shows the addable <select>; "edit" targets one provider
  // already in the list (rotate a secret, or change a url host).
  let formMode: "none" | "add" | "edit" = $state("none");
  let formProviderId = $state("");
  let formValue = $state("");
  let testing = $state(false);
  let testResult = $state<OllamaHostHealth | null>(null);

  const formDesc = $derived<ProviderDescriptor | null>(providerDescriptor(formProviderId));

  // A url credential is a non-sensitive host, so it seeds the edit field with the
  // current value (you tweak a host); a secret is never echoed back.
  function seedValue(desc: ProviderDescriptor | null): string {
    if (desc?.kind === "url") return (providers[desc.field] ?? "").trim();
    return "";
  }

  function resetForm() {
    formMode = "none";
    formProviderId = "";
    formValue = "";
    testing = false;
    testResult = null;
  }

  function beginAdd() {
    if (addable.length === 0) return;
    formMode = "add";
    formProviderId = addable[0].id;
    formValue = seedValue(providerDescriptor(addable[0].id));
    testResult = null;
  }

  function onAddSelect(id: string) {
    formProviderId = id;
    formValue = seedValue(providerDescriptor(id));
    testResult = null;
  }

  function beginEdit(id: string) {
    formMode = "edit";
    formProviderId = id;
    formValue = seedValue(providerDescriptor(id));
    testResult = null;
  }

  function canEdit(desc: ProviderDescriptor): boolean {
    // A host must always be changeable; a secret only in editable (Settings) mode.
    return desc.kind === "url" || editable;
  }

  function canRemove(desc: ProviderDescriptor): boolean {
    return editable && desc.removable;
  }

  async function commit() {
    const field = providerField(formProviderId);
    const value = formValue.trim();
    if (!field || !value) return;
    await onSaveKey(field, value);
    resetForm();
  }

  function remove(id: string) {
    const field = providerField(id);
    if (field && onClearKey) onClearKey(field);
  }

  async function runTest() {
    if (testing || !onTestReachability) return;
    const tested = formValue.trim();
    if (!tested) return;
    testing = true;
    testResult = null;
    try {
      const result = await onTestReachability(formProviderId, tested);
      // Drop a verdict that resolved after the field changed (stale).
      if (formValue.trim() === tested) testResult = result;
    } catch {
      if (formValue.trim() === tested) {
        testResult = { host: tested, reachable: false, latency_ms: 0, error: "The check couldn't run." };
      }
    } finally {
      testing = false;
    }
  }

  // The host shown as a muted detail on a url chip (a URL is not sensitive and is
  // useful to see at a glance — "is this pointing at my Pi?"). Secrets never show.
  function chipDetail(id: string): string {
    const desc = providerDescriptor(id);
    if (desc?.kind === "url") return (providers[desc.field] ?? "").trim();
    return "";
  }
</script>

<div class="provider-subs">
  {#if configured.length > 0}
    <div class="chip-tags">
      {#each configured as prov (prov.id)}
        {@const desc = providerDescriptor(prov.id)}
        <span class="chip-tag" class:is-active={prov.id === defaultProviderId}>
          <span class="chip-tag-label">{prov.label}</span>
          {#if chipDetail(prov.id)}
            <span class="chip-tag-detail">{chipDetail(prov.id)}</span>
          {/if}
          {#if desc && canEdit(desc)}
            <button
              type="button"
              class="chip-tag-btn"
              title={`Edit ${prov.label}`}
              aria-label={`Edit ${prov.label}`}
              disabled={busy}
              onclick={() => beginEdit(prov.id)}
            ><i class="ti ti-pencil" aria-hidden="true"></i></button>
          {/if}
          {#if desc && canRemove(desc)}
            <button
              type="button"
              class="chip-tag-btn is-remove"
              title={`Remove ${prov.label}`}
              aria-label={`Remove ${prov.label}`}
              disabled={busy}
              onclick={() => remove(prov.id)}
            ><i class="ti ti-x" aria-hidden="true"></i></button>
          {/if}
        </span>
      {/each}
    </div>
  {:else}
    <p class="muted">No providers available under this project's policy.</p>
  {/if}

  {#if formMode !== "none"}
    <div class="inline-form">
      {#if formMode === "add"}
        <label>
          Provider
          <select value={formProviderId} onchange={(e) => onAddSelect((e.currentTarget as HTMLSelectElement).value)}>
            {#each addable as prov (prov.id)}
              <option value={prov.id}>{prov.label}</option>
            {/each}
          </select>
        </label>
      {:else}
        <div class="edit-target">
          {formDesc?.kind === "url" ? "Host" : "Change key"} —
          <strong>{formDesc?.label ?? formProviderId}</strong>
        </div>
      {/if}
      <label>
        {formDesc?.kind === "url" ? "Host URL" : "API key"}
        <input
          type={formDesc?.kind === "url" ? "text" : "password"}
          autocomplete="off"
          bind:value={formValue}
          oninput={() => (testResult = null)}
          placeholder={providerPlaceholder(formProviderId)}
        />
      </label>
      {#if formDesc?.hasReachabilityTest && onTestReachability}
        <div class="test-row">
          <button type="button" disabled={testing || !formValue.trim()} onclick={runTest}>
            {testing ? "Testing…" : "Test host"}
          </button>
          {#if testResult}
            <span class="test-result" class:ok={testResult.reachable} class:fail={!testResult.reachable}>
              {#if testResult.reachable}
                ✓ Reached{#if testResult.version} · Ollama {testResult.version}{/if} · {testResult.latency_ms} ms
              {:else}
                ✗ {testResult.error}
              {/if}
            </span>
          {/if}
        </div>
      {/if}
      <div class="inline-form-actions">
        <button type="button" onclick={resetForm}>Cancel</button>
        <button type="button" class="primary" disabled={busy || !formValue.trim()} onclick={commit}
          >Save</button
        >
      </div>
    </div>
  {:else if addable.length > 0}
    <button type="button" class="inline-add-btn" onclick={beginAdd}>+ Add provider</button>
  {/if}
</div>

<style>
  /* Chips + inline form use the shared .chip-tag* / .inline-form* primitives in
     styles.css (#619). Only the pieces specific to this surface live here. */
  .provider-subs {
    display: grid;
    gap: 10px;
  }

  .chip-tag-detail {
    margin-left: 6px;
    color: var(--text-3);
    font-size: var(--fs-sm);
    font-family: var(--mono);
  }

  .edit-target {
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  .test-row {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .test-result {
    font-size: var(--fs-sm);
    color: var(--text-3);
  }

  .test-result.ok {
    color: var(--accent-deep);
  }

  .test-result.fail {
    color: var(--danger);
  }
</style>
