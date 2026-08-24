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

  import { onMount } from "svelte";
  import { api } from "@/lib/api";
  import { eligibleProviders, PROVIDER_DISPLAY_NAMES } from "@/lib/utils/aiProviders";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import ViewNodeList, { type RowCtx } from "@/components/widgets/ViewNodeList.svelte";
  import {
    modelInfoToEvalNodes,
    modelPickerView,
    type ModelEvalNode,
  } from "@/lib/views/modelNodes";
  import type {
    AICapabilityTier,
    AIModelInfo,
    AIPolicy,
    AIProviderInfo,
  } from "@/lib/types";

  let {
    provider = $bindable(""),
    // Empty string = "explicit-model mode" (Advanced is the source of truth).
    tier = $bindable(""),
    model = $bindable(""),
    // ADR-0073 S2: the caller's resolved AI policy (never "inherit" — the
    // caller folds that before passing down). Scopes the provider list to what
    // this policy + this machine's credentials actually permit, and picks the
    // default for a fresh entry — the picker no longer self-defaults to the
    // alphabetically-first known provider regardless of policy/credentials.
    policy,
    // Emitted with the literal provider/tier/model the entry should store; the
    // parent writes all three back (was a `change` CustomEvent before the runes
    // pass). provider/tier/model are `$bindable` because the picker reassigns
    // them internally (onMount defaulting, provider/tier/model changes) — a
    // non-bindable prop cannot be reassigned in runes mode. No parent binds
    // them today; they are passed one-way and updated via onChange.
    onChange = () => {},
  }: {
    provider?: string;
    tier?: AICapabilityTier | "";
    model?: string;
    policy: AIPolicy;
    onChange?: (detail: {
      provider: string;
      tier: AICapabilityTier | "";
      model: string;
    }) => void;
  } = $props();

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

  let providers = $state<AIProviderInfo[]>([]);
  let models = $state<AIModelInfo[]>([]);
  let modelsLoading = $state(false);
  let modelsError = $state("");
  let advancedOpen = $state(false);

  onMount(async () => {
    try {
      const ms = await api.getMachineSettings();
      const eligible = eligibleProviders(policy, ms.providers);
      providers = eligible.map((name) => ({
        name,
        display_name: PROVIDER_DISPLAY_NAMES[name] ?? name,
      }));
      if (!provider) {
        // Default a fresh entry to the machine default provider when the
        // policy permits it, else the first eligible provider — never the
        // alphabetically-first known provider regardless of policy.
        provider = eligible.includes(ms.default_provider) ? ms.default_provider : (eligible[0] ?? "");
        if (provider) emitChange();
      }
    } catch (e) {
      // Machine settings is local — no network. If this fails the backend is
      // down; let the parent handle the empty state.
    }
    if (provider) await loadModels();
  });

  // Returns the freshly-loaded list so callers can resolve against it
  // directly, rather than reading the derived `tierResolutions`/`visibleTiers`
  // back (which recompute from `models` and invite a stale-read window).
  async function loadModels(forceRefresh = false): Promise<AIModelInfo[]> {
    if (!provider) {
      models = [];
      return models;
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
    return models;
  }

  // Tiers that have at least one candidate model — these are the only
  // tiers worth surfacing in the dropdown (no point offering REASONING
  // when the provider has no thinking models).
  const availableTiers = $derived(
    TIER_ORDER.filter((t) => models.some((m) => m.tier === t && !m.deprecated)),
  );

  // The model the resolver picks for a tier: cheapest non-deprecated
  // candidate, tie-broken on the widest context window. Mirrors the backend's
  // `model_for_tier`. A PURE function over an explicit model list — both the
  // reactive `tierResolutions` map (for the dropdown) and the post-load
  // provider default (`onProviderChange`) resolve tiers through this, from the
  // same freshly-loaded data, so neither can pick against a stale catalogue.
  function resolveTier(list: AIModelInfo[], t: AICapabilityTier): AIModelInfo | null {
    const candidates = list
      .filter((m) => m.tier === t && !m.deprecated)
      .slice()
      .sort((a, b) => {
        const ac = a.cost_in_per_mtok ?? Infinity;
        const bc = b.cost_in_per_mtok ?? Infinity;
        if (ac !== bc) return ac - bc;
        return b.context_window - a.context_window;
      });
    return candidates[0] ?? null;
  }

  // For each available tier, the model the resolver will pick — used to render
  // "⚖ Balanced — Sonnet 4.6" in the dropdown, without a round-trip per tier.
  const tierResolutions = $derived.by(() => {
    const out: Partial<Record<AICapabilityTier, AIModelInfo | null>> = {};
    for (const t of TIER_ORDER) {
      out[t] = resolveTier(models, t);
    }
    return out;
  });

  // Hide LOCAL tier from non-Ollama providers and non-LOCAL tiers
  // from Ollama. Keeps the picker focused on what's actually useful
  // for the current provider.
  const visibleTiers = $derived(
    availableTiers.filter((t) =>
      provider === "ollama" ? t === "local" : t !== "local",
    ),
  );

  const currentResolvedModel = $derived(
    tier ? (tierResolutions[tier as AICapabilityTier]?.id ?? "") : "",
  );

  // If we have a tier set but the resolved model differs from the
  // stored one, the user picked an explicit override at some point —
  // flip to "custom" mode to surface that in the UI.
  const isCustom = $derived(
    !tier ||
      (Boolean(model) && Boolean(currentResolvedModel) && model !== currentResolvedModel),
  );

  async function onProviderChange(newProvider: string) {
    provider = newProvider;
    // Switching provider: clear tier + model and reload. The user
    // re-picks tier (or it stays empty for explicit-model mode).
    tier = "";
    model = "";
    // Try to default to BALANCED on the new provider (LOCAL for Ollama).
    // Resolve straight from the list `loadModels` just returned, NOT from the
    // derived `tierResolutions`/`visibleTiers` — reading those back here would
    // reintroduce the stale-catalogue window the fresh list exists to close.
    const loaded = await loadModels();
    const fallback: AICapabilityTier = provider === "ollama" ? "local" : "balanced";
    const resolved = resolveTier(loaded, fallback);
    if (resolved) {
      tier = fallback;
      model = resolved.id;
    }
    emitChange();
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
    onChange({ provider, tier, model });
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

  // A stored provider the current policy no longer permits (e.g. the policy
  // tightened after the entry was saved) — still offered so editing doesn't
  // silently drop it, but flagged rather than presented as a live option.
  const providerNotEligible = $derived(
    Boolean(provider) && !providers.some((p) => p.name === provider),
  );

  // ADR-0073 S3: the "Advanced" exact-model list is a fixed, read-only built-in
  // View over the provider's live catalogue — the app's own View machinery, not
  // a bespoke dropdown. Grouped by family, searchable (the ~300-model OpenRouter
  // wall was the reported pain), each row badged with tier/free plus a
  // context/price detail line. No drag/rename/add handlers are wired, so the
  // ViewNodeList interactivity gates stay dormant (read-only).
  const modelView = $derived({
    spec: modelPickerView(),
    universe: modelInfoToEvalNodes(models),
    schema: null,
  });

  function modelMatches(node: ModelEvalNode, query: string): boolean {
    // `query` arrives pre-normalized (trimmed + lowercased) from ViewNodeList.
    return (
      node.id.toLowerCase().includes(query) ||
      node.display_name.toLowerCase().includes(query) ||
      node.family.toLowerCase().includes(query)
    );
  }

  function modelRowTags(m: AIModelInfo): string[] {
    const tags: string[] = [m.tier];
    if (m.free) tags.push("free");
    // ADR-0073 S4: a live model with no hand-audited entry, tier derived — flag
    // it so the user knows its metadata is unverified.
    if (!m.verified) tags.push("new");
    if (m.deprecated) tags.push("deprecated");
    return tags;
  }
</script>

<div class="provider-tier-picker">
  {#if providers.length === 0 && !providerNotEligible}
    <p class="ptp-nudge">
      No AI providers available under this project's policy — add a key in
      Settings, or the policy is off/local-only.
    </p>
  {:else}
    <label class="ptp-row">
      <span class="ptp-label">Subscription</span>
      <select
        value={provider}
        onchange={(e) => onProviderChange((e.currentTarget as HTMLSelectElement).value)}
      >
        {#if providerNotEligible}
          <option value={provider}>
            {PROVIDER_DISPLAY_NAMES[provider] ?? provider} (not allowed by policy)
          </option>
        {/if}
        {#each providers as p (p.name)}
          <option value={p.name}>{p.display_name}</option>
        {/each}
      </select>
    </label>
  {/if}

  <label class="ptp-row">
    <span class="ptp-label">Capability</span>
    <select
      value={isCustom ? "" : tier}
      disabled={modelsLoading || visibleTiers.length === 0}
      onchange={(e) => onTierChange((e.currentTarget as HTMLSelectElement).value as AICapabilityTier | "")}
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
    <summary>Advanced — browse all models</summary>
    {#if model && !models.some((m) => m.id === model)}
      <!-- Persisted model not in the current catalogue — surface it so the user
           sees what the entry is bound to, even though it's effectively orphaned
           (provider may have sunset it, or live discovery is offline). -->
      <p class="ptp-orphan">
        Bound to <code>{model}</code>, which isn't in the current catalogue.
      </p>
    {/if}
    <div class="ptp-model-list">
      <ViewNodeList
        view={modelView}
        density="compact"
        searchPlaceholder="Search models…"
        filter={modelMatches}
        active={(node) => node.id === model}
        onClick={(node) => onModelChange(node.id)}
        row={modelRow}
      >
        {#snippet whenEmpty()}
          <p class="ptp-nudge">
            {modelsLoading ? "Loading models…" : modelsError || "No models."}
          </p>
        {/snippet}
      </ViewNodeList>
    </div>
    <div class="ptp-meta">
      <button type="button" class="ptp-refresh" onclick={() => loadModels(true)} disabled={modelsLoading}>
        Refresh models
      </button>
    </div>
  </details>
</div>

{#snippet modelRow(m: ModelEvalNode, ctx: RowCtx<ModelEvalNode>)}
  <NodeRow
    title={m.display_name}
    depth={ctx.depth}
    active={ctx.active}
    onClick={ctx.onClick}
    tags={modelRowTags(m)}
  >
    {#snippet detailSlot()}
      <small class="ptp-model-detail">
        {m.context_window > 0 ? `${(m.context_window / 1000).toFixed(0)}k context` : ""}
        {#if m.cost_in_per_mtok}{m.context_window > 0 ? " · " : ""}{fmtCost(m.cost_in_per_mtok)}{/if}
        {#if m.capabilities.includes("vision")} · vision{/if}
        {#if m.capabilities.includes("thinking")} · thinks{/if}
        {#if m.capabilities.includes("caching")} · caches{/if}
      </small>
    {/snippet}
  </NodeRow>
{/snippet}

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

  .ptp-nudge {
    margin: 0;
    color: var(--text-3);
    font-size: var(--fs-sm);
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

  .ptp-model-list {
    margin-top: 6px;
    max-height: 320px;
    overflow-y: auto;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--surface);
  }

  .ptp-orphan {
    margin: 6px 0 0;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }

  .ptp-orphan code {
    font-family: var(--mono);
  }
</style>
