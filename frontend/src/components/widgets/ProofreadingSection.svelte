<script lang="ts">
  // Settings → Proofreading (ADR-0102 §4): per level — Library, machine, each
  // project in the chain — the dialect, the rule switches and the dictionary.
  // Like the Assistants tab it owns its API calls and writes at once, with no
  // Save: every change is a file write the lens loads the answer of.
  import { onMount } from "svelte";
  import ProofreadingRules from "@/components/widgets/ProofreadingRules.svelte";
  import type { RuleGroup } from "@/lib/proofread/findings";
  import { HARPER_DEFAULT, changedRuleNames, filterGroups, inheritedDialect } from "@/lib/proofread/settingsView";
  import { proofreading } from "@/lib/stores/proofreading.svelte";
  import type { ProofreadingDialect } from "@/lib/types";

  let { projectOpen = false }: { projectOpen?: boolean } = $props();

  const DIALECTS: { value: ProofreadingDialect; label: string }[] = [
    { value: "american", label: "American" },
    { value: "british", label: "British" },
    { value: "australian", label: "Australian" },
    { value: "canadian", label: "Canadian" },
    { value: "indian", label: "Indian" },
  ];
  const dialectLabel = (d: ProofreadingDialect) => DIALECTS.find((x) => x.value === d)?.label ?? d;

  let groups = $state.raw<RuleGroup[] | null>(null);
  let loadError = $state("");
  let error = $state("");
  let selectedId = $state("");
  let busy = $state(new Set<string>());
  let query = $state("");
  let changedOnly = $state(false);

  const setup = $derived(proofreading.setup);
  const layer = $derived(setup?.layers.find((l) => l.id === selectedId) ?? null);
  const readonly = $derived(layer?.is_library ?? false);
  const filtering = $derived(query.trim() !== "" || changedOnly);
  const shown = $derived(groups && setup ? filterGroups(groups, query, changedOnly, changedRuleNames(setup)) : []);
  const inherited = $derived(setup && layer ? inheritedDialect(setup, layer.id) : null);

  onMount(() => {
    if (!projectOpen) return;
    void (async () => {
      try {
        const [catalog] = await Promise.all([proofreading.catalog(), proofreading.refreshSetup()]);
        groups = catalog;
      } catch (err) {
        loadError = err instanceof Error ? err.message : String(err);
      }
    })();
  });

  // Default to the open project; keep a choice that still exists.
  $effect(() => {
    const layers = setup?.layers ?? [];
    if (layers.some((l) => l.id === selectedId)) return;
    selectedId = (layers.find((l) => l.is_root) ?? layers[layers.length - 1])?.id ?? "";
  });

  async function write(key: string, fn: () => Promise<void>): Promise<void> {
    busy = new Set(busy).add(key);
    error = "";
    try {
      await fn();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      const next = new Set(busy);
      next.delete(key);
      busy = next;
    }
  }

  function onDialect(event: Event): void {
    if (!layer) return;
    const value = (event.currentTarget as HTMLSelectElement).value;
    const dialect = value === "" ? null : (value as ProofreadingDialect);
    void write("dialect", () => proofreading.setDialect(dialect, layer.id));
  }
</script>

{#if !projectOpen}
  <p class="muted">Open a project to set up proofreading.</p>
{:else}
  <section class="proofreading">
    {#if loadError}
      <p class="error">{loadError}</p>
    {:else if !groups || !setup || !layer}
      <p class="muted">Loading the checker…</p>
    {:else}
      <label class="field">
        Level
        <select bind:value={selectedId} aria-label="Level">
          {#each setup.layers as l (l.id)}
            <option value={l.id}>{l.label}</option>
          {/each}
        </select>
      </label>
      {#if readonly}
        <p class="muted">The built-in fiction default is read-only; override it on this machine or a project.</p>
      {/if}
      {#if error}<p class="error">{error}</p>{/if}

      <h3>Dialect</h3>
      <select aria-label="Dialect" value={layer.dialect ?? ""} disabled={readonly || busy.has("dialect")} onchange={onDialect}>
        <option value="">
          Inherit ({dialectLabel(inherited?.dialect ?? "american")}, {inherited?.from === HARPER_DEFAULT ? HARPER_DEFAULT : `from ${inherited?.from}`})
        </option>
        {#each DIALECTS as d (d.value)}
          <option value={d.value}>{d.label}</option>
        {/each}
      </select>

      <h3>Rules</h3>
      <div class="filters">
        <input type="search" placeholder="Search rules" aria-label="Search rules" bind:value={query} />
        <label class="check"><input type="checkbox" bind:checked={changedOnly} /> Changed only</label>
      </div>
      {#if shown.length === 0}
        <p class="muted">No rules match.</p>
      {:else}
        <ProofreadingRules
          groups={shown}
          {setup}
          {layer}
          {readonly}
          forceOpen={filtering}
          {busy}
          onSet={(rule, enabled) => void write(rule, () => proofreading.setRule(rule, enabled, layer.id))}
        />
      {/if}

      <h3>Dictionary</h3>
      {#if layer.words.length === 0}
        <p class="muted">No words added at this level.</p>
      {:else}
        <ul class="words">
          {#each layer.words as word (word)}
            <li>
              <span>{word}</span>
              <button
                type="button"
                class="remove"
                aria-label={`Remove ${word}`}
                disabled={readonly || busy.has(`word:${word}`)}
                onclick={() => void write(`word:${word}`, () => proofreading.removeWord(word, layer.id))}
              >×</button>
            </li>
          {/each}
        </ul>
      {/if}
    {/if}
  </section>
{/if}

<style>
  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 8px;
  }

  h3 {
    margin: 14px 0 6px;
  }

  .filters {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 6px;
  }

  .filters input[type="search"] {
    flex: 1;
  }

  .check {
    display: flex;
    align-items: center;
    gap: 4px;
    color: var(--text-2);
    white-space: nowrap;
  }

  .error {
    color: var(--danger);
  }

  .words {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .words li {
    display: flex;
    align-items: center;
    gap: 4px;
    background: var(--inset);
    border-radius: 6px;
    padding: 2px 4px 2px 8px;
  }

  .remove {
    background: none;
    border: none;
    color: var(--text-3);
    padding: 0 4px;
  }
</style>
