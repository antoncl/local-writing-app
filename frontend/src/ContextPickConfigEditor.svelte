<script lang="ts">
  // Author-time config editor for a context_pick input.
  //
  // Lives inside the Inputs editor row in DocumentEditorPane when the
  // user picks type = "Context picker". Edits the four config fields:
  // kinds, entry_types per kind, presets, multiple. Emits the entire
  // config back via the `change` event.
  //
  // Per docs/context-picker.md "Author UI (config row)".

  import { createEventDispatcher } from "svelte";
  import type { ContextPickConfig, MetadataSchema } from "./types";

  export let config: ContextPickConfig;
  export let metadataSchema: MetadataSchema | null = null;

  const dispatch = createEventDispatcher<{ change: { config: ContextPickConfig } }>();

  type Kind = "scene" | "lore" | "snippet" | "assistant";
  const KINDS: { id: Kind; label: string }[] = [
    { id: "scene", label: "Scenes" },
    { id: "lore", label: "Lore" },
    { id: "snippet", label: "Snippets" },
    { id: "assistant", label: "Assistants" },
  ];

  const PRESETS: { id: "full_outline" | "full_text"; label: string }[] = [
    { id: "full_outline", label: "Full Outline" },
    { id: "full_text", label: "Full Novel Text" },
  ];

  $: kinds = new Set((config.kinds ?? []) as Kind[]);
  $: presets = new Set(config.presets ?? []);
  $: entryTypes = (config.entry_types ?? {}) as Record<string, string[]>;
  $: multiple = config.multiple !== false;

  // For each kind that's enabled and supports sub-types (lore / snippet),
  // surface the project's available sub-types so the author can narrow.
  // Scenes/assistants don't have meaningful sub-type filtering for v1.
  function subtypesForKind(kind: Kind): { id: string; label: string }[] {
    if (!metadataSchema) return [];
    return Object.entries(metadataSchema.entry_types)
      .filter(([, def]) => def.kind === kind && !def.abstract)
      .map(([id, def]) => ({ id, label: def.name || id }));
  }

  function toggleKind(kind: Kind, checked: boolean) {
    const next = new Set(kinds);
    if (checked) next.add(kind);
    else next.delete(kind);
    const nextEntryTypes = { ...entryTypes };
    if (!checked) delete nextEntryTypes[kind];
    emit({ kinds: Array.from(next), entry_types: nextEntryTypes });
  }

  function togglePreset(id: "full_outline" | "full_text", checked: boolean) {
    const next = new Set(presets);
    if (checked) next.add(id);
    else next.delete(id);
    emit({ presets: Array.from(next) });
  }

  function toggleSubtype(kind: Kind, subtypeId: string, checked: boolean) {
    const current = new Set(entryTypes[kind] ?? []);
    if (checked) current.add(subtypeId);
    else current.delete(subtypeId);
    const next = { ...entryTypes };
    if (current.size === 0) {
      // Empty = all sub-types allowed (no filter). Drop the key entirely
      // rather than carrying [] which means "none of them" elsewhere.
      delete next[kind];
    } else {
      next[kind] = Array.from(current);
    }
    emit({ entry_types: next });
  }

  function toggleMultiple(checked: boolean) {
    emit({ multiple: checked });
  }

  function emit(patch: Partial<ContextPickConfig>) {
    dispatch("change", { config: { ...config, ...patch } });
  }
</script>

<div class="ctx-config">
  <div class="ctx-config-section">
    <strong>Allow picks from</strong>
    {#each KINDS as kind (kind.id)}
      <label class="ctx-config-check">
        <input
          type="checkbox"
          checked={kinds.has(kind.id)}
          on:change={(e) => toggleKind(kind.id, (e.currentTarget as HTMLInputElement).checked)}
        />
        {kind.label}
      </label>
      {#if kinds.has(kind.id)}
        {@const subtypes = subtypesForKind(kind.id)}
        {#if subtypes.length > 0}
          <div class="ctx-config-subtypes">
            <small>Sub-types (none checked = all allowed):</small>
            {#each subtypes as sub (sub.id)}
              <label class="ctx-config-check ctx-config-check-inline">
                <input
                  type="checkbox"
                  checked={(entryTypes[kind.id] ?? []).includes(sub.id)}
                  on:change={(e) => toggleSubtype(kind.id, sub.id, (e.currentTarget as HTMLInputElement).checked)}
                />
                {sub.label}
              </label>
            {/each}
          </div>
        {/if}
      {/if}
    {/each}
  </div>

  <div class="ctx-config-section">
    <strong>Presets</strong>
    {#each PRESETS as preset (preset.id)}
      <label class="ctx-config-check">
        <input
          type="checkbox"
          checked={presets.has(preset.id)}
          on:change={(e) => togglePreset(preset.id, (e.currentTarget as HTMLInputElement).checked)}
        />
        {preset.label}
      </label>
    {/each}
  </div>

  <label class="ctx-config-check">
    <input
      type="checkbox"
      checked={multiple}
      on:change={(e) => toggleMultiple((e.currentTarget as HTMLInputElement).checked)}
    />
    Allow multiple picks
  </label>
</div>

<style>
  .ctx-config {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 6px 8px;
    border: 1px dashed #cbd6d2;
    border-radius: 4px;
    background: #fafbfa;
    font-size: 12px;
  }

  .ctx-config-section {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .ctx-config-section > strong {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #65716c;
  }

  .ctx-config-check {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
  }

  .ctx-config-check-inline {
    margin-right: 8px;
  }

  .ctx-config-subtypes {
    margin-left: 22px;
    padding: 4px 6px;
    border-left: 2px solid #d8dfdd;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .ctx-config-subtypes small {
    color: #65716c;
  }
</style>
