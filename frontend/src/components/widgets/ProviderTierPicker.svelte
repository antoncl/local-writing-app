<script lang="ts">
  // Tier-first picker for the Assistant builder.
  //
  // Provider → Capability tier → (Advanced) exact model. The tier
  // dropdown shows what model it currently resolves to so the user sees
  // the consequence of their choice. Picking a specific model under
  // Advanced clears the tier ("Custom"). Save-time resolution: this
  // component emits a `change` event with the literal provider, tier,
  // and model the entry should store. App.svelte writes all three
  // back into the assistant entry's metadata.
  //
  // Per docs/ai-model-selection.md.

  import { onMount, createEventDispatcher } from "svelte";
  import { api } from "@/lib/api";
  import type {
    AICapabilityTier,
    AIModelInfo,
    AIProviderInfo,
  } from "@/lib/types";

  export let provider: string = "";
  // Empty string = "explicit-model mode" (Advanced is the source of truth).
  export let tier: AICapabilityTier | "" = "";
  export let model: string = "";

  const dispatch = createEventDispatcher<{
    change: { provider: string; tier: AICapabilityTier | ""; model: string };
  }>();

  // Tier display order. LOCAL deliberately last; it's Ollama-only.
  const TIER_ORDER: AICapabilityTier[] = [
    "fast",
    "balanced",
    "premium",
    "reasoning",
    "local",
  ];
  const TIER_LABELS: Record<AICapabilityTier, string> = {
    fast: "⚡ Fast",
    balanced: "⚖ Balanced",
    premium: "✨ Premium",
    reasoning: "🧠 Reasoning",
    local: "💻 Local",
  };

  let providers: AIProviderInfo[] = [];
  let models: AIModelInfo[] = [];
  let modelsLoading = false;
  let modelsError = "";
  let advancedOpen = false;

  onMount(async () => {
    try {
      const list = await api.listAIProviders();
      providers = list.providers;
      if (!provider && providers.length > 0) {
        // Default to the first known provider when the entry is fresh.
        provider = providers[0].name;
        emitChange();
      }
    } catch (e) {
      // Provider listing is local — no network. If this fails the
      // backend is down; let the parent handle the empty state.
    }
    if (provider) await loadModels();
  });

  async function loadModels(forceRefresh = false) {
    if (!provider) {
      models = [];
      return;
    }
    modelsLoading = true;
    modelsError = "";
    try {
      const list = await api.listAIProviderModels(provider, forceRefresh);
      models = list.models;
    } catch (e) {
      modelsError = (e as Error).message || "Couldn't load models.";
      models = [];
    } finally {
      modelsLoading = false;
    }
  }

  // Tiers that have at least one candidate model — these are the only
  // tiers worth surfacing in the dropdown (no point offering REASONING
  // when the provider has no thinking models).
  $: availableTiers = TIER_ORDER.filter((t) =>
    models.some((m) => m.tier === t && !m.deprecated),
  );

  // For each available tier, the model the resolver will pick — used
  // to render "⚖ Balanced — Sonnet 4.6" in the dropdown. Mirrors the
  // backend's `model_for_tier` (cheapest non-deprecated, tie-break on
  // context window). Computed client-side so the dropdown can show
  // the resolved name without a round-trip per tier.
  $: tierResolutions = (() => {
    const out: Partial<Record<AICapabilityTier, AIModelInfo | null>> = {};
    for (const t of TIER_ORDER) {
      const candidates = models
        .filter((m) => m.tier === t && !m.deprecated)
        .slice()
        .sort((a, b) => {
          const ac = a.cost_in_per_mtok ?? Infinity;
          const bc = b.cost_in_per_mtok ?? Infinity;
          if (ac !== bc) return ac - bc;
          return b.context_window - a.context_window;
        });
      out[t] = candidates[0] ?? null;
    }
    return out;
  })();

  // Hide LOCAL tier from non-Ollama providers and non-LOCAL tiers
  // from Ollama. Keeps the picker focused on what's actually useful
  // for the current provider.
  $: visibleTiers = availableTiers.filter((t) =>
    provider === "ollama" ? t === "local" : t !== "local",
  );

  $: currentResolvedModel = tier ? tierResolutions[tier as AICapabilityTier]?.id ?? "" : "";

  // If we have a tier set but the resolved model differs from the
  // stored one, the user picked an explicit override at some point —
  // flip to "custom" mode to surface that in the UI.
  $: isCustom = !tier || (Boolean(model) && Boolean(currentResolvedModel) && model !== currentResolvedModel);

  async function onProviderChange(newProvider: string) {
    provider = newProvider;
    // Switching provider: clear tier + model and reload. The user
    // re-picks tier (or it stays empty for explicit-model mode).
    tier = "";
    model = "";
    await loadModels();
    // Try to default to BALANCED on the new provider if available,
    // else LOCAL for Ollama.
    const fallback: AICapabilityTier = provider === "ollama" ? "local" : "balanced";
    if (visibleTiers.includes(fallback)) {
      onTierChange(fallback);
    } else {
      emitChange();
    }
  }

  function onTierChange(newTier: AICapabilityTier | "") {
    tier = newTier;
    if (newTier && tierResolutions[newTier]) {
      model = tierResolutions[newTier]!.id;
    }
    emitChange();
  }

  function onModelChange(newModel: string) {
    model = newModel;
    // Picking an explicit model that doesn't match any tier resolution
    // means we're in "Custom" — clear the tier hint so save round-trips
    // honestly.
    const resolvedTiers = TIER_ORDER.filter(
      (t) => tierResolutions[t]?.id === newModel,
    );
    if (resolvedTiers.length === 0) {
      tier = "";
    }
    emitChange();
  }

  function emitChange() {
    dispatch("change", { provider, tier, model });
  }

  function fmtCost(cost: number | null | undefined): string {
    if (cost === null || cost === undefined) return "";
    return `$${cost.toFixed(cost < 1 ? 2 : 0)}/Mtok`;
  }

  function tierOptionLabel(t: AICapabilityTier): string {
    const resolved = tierResolutions[t];
    if (!resolved) return TIER_LABELS[t];
    return `${TIER_LABELS[t]} — ${resolved.display_name}`;
  }
</script>

<div class="provider-tier-picker">
  <label class="ptp-row">
    <span class="ptp-label">Subscription</span>
    <select
      value={provider}
      on:change={(e) => onProviderChange((e.currentTarget as HTMLSelectElement).value)}
    >
      {#if providers.length === 0}
        <option value="">(no providers)</option>
      {/if}
      {#each providers as p (p.name)}
        <option value={p.name}>{p.display_name}</option>
      {/each}
    </select>
  </label>

  <label class="ptp-row">
    <span class="ptp-label">Capability</span>
    <select
      value={isCustom ? "" : tier}
      disabled={modelsLoading || visibleTiers.length === 0}
      on:change={(e) => onTierChange((e.currentTarget as HTMLSelectElement).value as AICapabilityTier | "")}
    >
      <option value="">{isCustom ? "Custom (Advanced)" : "—"}</option>
      {#each visibleTiers as t (t)}
        <option value={t}>{tierOptionLabel(t)}</option>
      {/each}
    </select>
    {#if modelsLoading}
      <small class="ptp-status">loading…</small>
    {:else if modelsError}
      <small class="ptp-status ptp-error">{modelsError}</small>
    {/if}
  </label>

  <details bind:open={advancedOpen} class="ptp-advanced">
    <summary>Advanced</summary>
    <label class="ptp-row">
      <span class="ptp-label">Model</span>
      <select
        value={model}
        on:change={(e) => onModelChange((e.currentTarget as HTMLSelectElement).value)}
      >
        {#if model && !models.some((m) => m.id === model)}
          <!-- Persisted model not in current catalogue — show it so
               the user can see what the entry is currently bound to,
               but it's effectively orphaned (provider may have
               sunset it, or live discovery is offline). -->
          <option value={model}>{model} (unknown)</option>
        {/if}
        {#each models as m (m.id)}
          <option value={m.id}>
            {m.display_name}{m.deprecated ? " (deprecated)" : ""}{m.cost_in_per_mtok ? ` · ${fmtCost(m.cost_in_per_mtok)}` : ""}
          </option>
        {/each}
      </select>
    </label>
    <div class="ptp-meta">
      <button type="button" class="ptp-refresh" on:click={() => loadModels(true)} disabled={modelsLoading}>
        Refresh models
      </button>
      {#if model}
        {@const current = models.find((m) => m.id === model)}
        {#if current}
          <small class="ptp-model-detail">
            {current.context_window > 0 ? `${(current.context_window / 1000).toFixed(0)}k context` : ""}
            {#if current.capabilities.includes("caching")} · caches{/if}
            {#if current.capabilities.includes("vision")} · vision{/if}
            {#if current.capabilities.includes("thinking")} · thinks{/if}
          </small>
        {/if}
      {/if}
    </div>
  </details>
</div>

<style>
  .provider-tier-picker {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--inset);
    color: var(--text);
    font-size: var(--fs-md);
  }

  .ptp-row {
    display: grid;
    grid-template-columns: 110px 1fr auto;
    align-items: center;
    gap: 8px;
  }

  .ptp-label {
    color: var(--text-2);
    font-weight: 500;
  }

  .ptp-status {
    font-size: var(--fs-sm);
    color: var(--text-3);
  }

  .ptp-error {
    color: var(--danger);
  }

  .ptp-advanced {
    border-top: 1px dashed var(--border);
    padding-top: 6px;
  }

  .ptp-advanced > summary {
    cursor: pointer;
    color: var(--text-2);
    font-weight: 500;
    user-select: none;
  }

  .ptp-meta {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 6px;
    padding-left: 118px;
  }

  .ptp-refresh {
    padding: 2px 8px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text-2);
    border-radius: 4px;
    font-size: var(--fs-sm);
    cursor: pointer;
  }

  .ptp-refresh:hover:not(:disabled) {
    background: var(--surface);
  }

  .ptp-model-detail {
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
</style>
