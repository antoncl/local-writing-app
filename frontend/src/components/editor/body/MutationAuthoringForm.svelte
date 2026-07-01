<script lang="ts" module>
  export type MutationDraft = { entity: string; field: string; value: string };
</script>

<script lang="ts">
  // Authoring form for the `/mutate` slash command (#33, #56). Picks a lore
  // entity, one or more of its fields (a promotion sets rank + title + uniform
  // → N independent markers, §2.1), and a value per field using that field
  // type's own input. Emits one MutationDraft per selected field; the caller
  // inserts a pill (with a client-minted id) for each at the cursor.
  import type { LoreEntrySummary, MetadataFieldDefinition, MetadataSchema } from "@/lib/types";

  let {
    loreEntries = [],
    schema = null,
    onSubmit,
    onCancel,
  }: {
    loreEntries: LoreEntrySummary[];
    schema: MetadataSchema | null;
    onSubmit: (drafts: MutationDraft[]) => void;
    onCancel: () => void;
  } = $props();

  let entityId = $state("");
  // field id -> { selected, value }
  let picks = $state<Record<string, { on: boolean; value: string }>>({});

  const entity = $derived(loreEntries.find((e) => e.id === entityId) ?? null);

  // The entity's mutable fields: its resolved schema fields (minus computed,
  // which are derived) plus the intrinsic `title` (the name-change case). No
  // schema-edit step — every field is mutable (ADR-0004).
  const fieldOptions = $derived.by((): Array<{ id: string; label: string; def: MetadataFieldDefinition | null }> => {
    if (!entity) return [];
    const ids = schema?.entry_types[entity.entry_type]?.fields ?? [];
    const opts: Array<{ id: string; label: string; def: MetadataFieldDefinition | null }> = [
      { id: "title", label: "Title (name)", def: null },
    ];
    for (const id of ids) {
      const def = schema?.fields[id] ?? null;
      // Computed fields are derived; collection fields (multi_select / tags /
      // entity_ref_list) are additive-flavored and land in v1.1 — offering them
      // here would only produce a save-blocking 422 on a scalar value.
      if (def && ["computed", "multi_select", "tags", "entity_ref_list"].includes(def.type)) continue;
      opts.push({ id, label: def?.name ?? id, def });
    }
    return opts;
  });

  // Lore entries offered for an entity_ref field's picker, honoring its
  // picker_config target kinds/entry_types when present.
  function refCandidates(def: MetadataFieldDefinition | null) {
    const kinds = def?.picker_config?.kinds;
    const entryTypes = def?.picker_config?.entry_types;
    return loreEntries.filter((e) => {
      if (kinds && kinds.length > 0 && !kinds.includes("lore")) return false;
      const allowed = entryTypes?.lore;
      if (allowed && allowed.length > 0 && !allowed.includes(e.entry_type)) return false;
      return true;
    });
  }

  const canSubmit = $derived(
    Boolean(entity) &&
      fieldOptions.some((f) => picks[f.id]?.on && (picks[f.id]?.value ?? "").length > 0),
  );

  function toggle(id: string, on: boolean) {
    picks[id] = { on, value: picks[id]?.value ?? "" };
  }

  function setValue(id: string, value: string) {
    picks[id] = { on: picks[id]?.on ?? true, value };
  }

  function submit() {
    if (!entity) return;
    const drafts: MutationDraft[] = [];
    for (const f of fieldOptions) {
      const pick = picks[f.id];
      if (pick?.on && (pick.value ?? "").length > 0) {
        drafts.push({ entity: entity.id, field: f.id, value: pick.value });
      }
    }
    if (drafts.length > 0) onSubmit(drafts);
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
    } else if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && canSubmit) {
      event.preventDefault();
      submit();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="mutation-overlay" role="presentation" onclick={onCancel}>
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div
    class="mutation-card"
    role="dialog"
    aria-label="Record lore mutation"
    tabindex="-1"
    onclick={(e) => e.stopPropagation()}
  >
    <header class="mutation-head">
      <h3>Record lore mutation</h3>
      <p>The change takes effect here and in every later scene.</p>
    </header>

    <label class="mutation-row">
      <span class="mutation-label">Entity</span>
      <select bind:value={entityId}>
        <option value="" disabled>Pick a lore entry…</option>
        {#each loreEntries as e (e.id)}
          <option value={e.id}>{e.title || e.id}</option>
        {/each}
      </select>
    </label>

    {#if entity}
      <div class="mutation-fields">
        {#each fieldOptions as f (f.id)}
          <div class="mutation-field">
            <label class="mutation-check">
              <input
                type="checkbox"
                checked={picks[f.id]?.on ?? false}
                onchange={(e) => toggle(f.id, e.currentTarget.checked)}
              />
              <span>{f.label}</span>
            </label>
            {#if picks[f.id]?.on}
              {#if f.def?.type === "select"}
                <select
                  value={picks[f.id]?.value ?? ""}
                  onchange={(e) => setValue(f.id, e.currentTarget.value)}
                >
                  <option value="" disabled>Choose…</option>
                  {#each f.def.options ?? [] as opt}
                    {@const optValue = typeof opt === "string" ? opt : opt.value}
                    {@const optLabel = typeof opt === "string" ? opt : (opt.label ?? opt.value)}
                    <option value={optValue}>{optLabel}</option>
                  {/each}
                </select>
              {:else if f.def?.type === "entity_ref"}
                <select
                  value={picks[f.id]?.value ?? ""}
                  onchange={(e) => setValue(f.id, e.currentTarget.value)}
                >
                  <option value="" disabled>Choose…</option>
                  {#each refCandidates(f.def) as e (e.id)}
                    <option value={e.id}>{e.title || e.id}</option>
                  {/each}
                </select>
              {:else if f.def?.type === "boolean"}
                <select
                  value={picks[f.id]?.value ?? ""}
                  onchange={(e) => setValue(f.id, e.currentTarget.value)}
                >
                  <option value="" disabled>Choose…</option>
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              {:else if f.def?.type === "number"}
                <input
                  type="number"
                  value={picks[f.id]?.value ?? ""}
                  oninput={(e) => setValue(f.id, e.currentTarget.value)}
                  placeholder="New value"
                />
              {:else}
                <input
                  type="text"
                  value={picks[f.id]?.value ?? ""}
                  oninput={(e) => setValue(f.id, e.currentTarget.value)}
                  placeholder="New value"
                />
              {/if}
            {/if}
          </div>
        {/each}
      </div>
    {/if}

    <footer class="mutation-foot">
      <button type="button" class="ghost" onclick={onCancel}>Cancel</button>
      <button type="button" class="primary" disabled={!canSubmit} onclick={submit}>
        Insert mutation
      </button>
    </footer>
  </div>
</div>

<style>
  .mutation-overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.28);
  }
  .mutation-card {
    width: min(440px, 92vw);
    max-height: 82vh;
    overflow-y: auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.24);
    padding: 18px;
  }
  .mutation-head h3 {
    margin: 0 0 2px;
    font-size: 1.05rem;
    color: var(--text);
  }
  .mutation-head p {
    margin: 0 0 14px;
    font-size: 0.82rem;
    color: var(--text-3);
  }
  .mutation-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 12px;
  }
  .mutation-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--text-2);
  }
  select,
  input {
    padding: 6px 8px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text);
    font: inherit;
  }
  .mutation-fields {
    display: flex;
    flex-direction: column;
    gap: 8px;
    border-top: 1px solid var(--border);
    padding-top: 12px;
    margin-bottom: 12px;
  }
  .mutation-field {
    display: grid;
    grid-template-columns: 1fr 1fr;
    align-items: center;
    gap: 8px;
  }
  .mutation-check {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.9rem;
    color: var(--text);
    cursor: pointer;
  }
  .mutation-foot {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
  button {
    padding: 7px 14px;
    border-radius: 6px;
    font: inherit;
    cursor: pointer;
    border: 1px solid var(--border);
  }
  button.ghost {
    background: transparent;
    color: var(--text-2);
  }
  button.primary {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
    font-weight: 600;
  }
  button.primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
