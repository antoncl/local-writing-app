<script lang="ts">
  // Runtime side of the context picker (v1).
  //
  // Renders a "+ <label>" button. Clicking opens a constrained menu
  // limited to the kinds / sub-types / presets the prompt author
  // declared in the `config`. Picked items render as chips above the
  // button with × buttons to remove.
  //
  // Stores only refs (id, kind, title) — bodies are materialized
  // server-side at template render time. See docs/context-picker.md.

  import { createEventDispatcher } from "svelte";
  import type {
    ContextPickConfig,
    ContextPickRef,
    LoreEntrySummary,
    MetadataSchema,
    PromptEntrySummary,
    StructureDocument,
    StructureNode,
  } from "./types";

  export let config: ContextPickConfig = {};
  export let value: ContextPickRef[] = [];
  export let label: string = "Context";
  export let structure: StructureDocument | null = null;
  export let loreEntries: LoreEntrySummary[] = [];
  export let promptEntries: PromptEntrySummary[] = [];
  export let metadataSchema: MetadataSchema | null = null;
  // Compact mode trims chrome so the picker fits inside the Inputs
  // dialog's narrow column. Composer-level renders use the default.
  export let compact: boolean = false;

  const dispatch = createEventDispatcher<{ change: { value: ContextPickRef[] } }>();

  type Category = "scene" | "lore" | "snippet" | "assistant";

  let open = false;
  let category: Category | null = null;
  let search = "";

  // Allowed presets per the author config — empty means no presets shown.
  $: allowedPresets = config.presets ?? [];
  // Allowed kinds per the author config — empty means no browse section.
  $: allowedKinds = (config.kinds ?? []) as Category[];
  $: allowMultiple = config.multiple !== false;

  const PRESET_META: Record<string, { title: string; tooltip: string }> = {
    full_outline: {
      title: "Full Outline",
      tooltip:
        "Include the manuscript outline (acts → chapters → scenes with summaries).",
    },
    full_text: {
      title: "Full Novel Text",
      tooltip: "Include every scene's prose in manuscript order. Can be large.",
    },
  };

  const KIND_LABELS: Record<Category, string> = {
    scene: "Scenes",
    lore: "Lore Entries",
    snippet: "Snippets",
    assistant: "Assistants",
  };

  function refKey(ref: ContextPickRef): string {
    return `${ref.kind}:${ref.id}`;
  }

  function isPicked(ref: ContextPickRef): boolean {
    return value.some((existing) => refKey(existing) === refKey(ref));
  }

  function add(ref: ContextPickRef) {
    if (isPicked(ref)) return;
    const next = allowMultiple ? [...value, ref] : [ref];
    dispatch("change", { value: next });
    if (!allowMultiple) close();
  }

  function remove(key: string) {
    dispatch("change", {
      value: value.filter((ref) => refKey(ref) !== key),
    });
  }

  function toggle() {
    open = !open;
    if (open) {
      search = "";
      // Skip the category-picker screen when there's exactly one source.
      // A picker that allows only scenes (or only lore) wastes a click
      // on a one-option menu; open straight to the leaf. Preset-only
      // configs already only have one option, so the same rule applies.
      const oneKind = allowedKinds.length === 1 && allowedPresets.length === 0;
      category = oneKind ? allowedKinds[0] : null;
    }
  }

  function close() {
    open = false;
    category = null;
    search = "";
  }

  function openCategory(c: Category) {
    category = c;
    search = "";
  }

  function backToCategories() {
    category = null;
    search = "";
  }

  function handleDocumentClick(event: MouseEvent) {
    const target = event.target as HTMLElement | null;
    if (open && !target?.closest(".ctx-picker-anchor")) close();
  }

  function handleKeydown(event: KeyboardEvent) {
    if (open && event.key === "Escape") {
      event.preventDefault();
      close();
    }
  }

  // Flatten the structure tree's scenes (entries with kind=scene) into a
  // searchable list, respecting the per-input sub-type filter so the
  // editor's checkbox actually does something (was a silent no-op).
  function flattenScenes(node: StructureNode | undefined): Array<{ id: string; title: string; entry_type: string }> {
    if (!node) return [];
    const allowed = new Set(config.entry_types?.scene ?? []);
    const out: Array<{ id: string; title: string; entry_type: string }> = [];
    const walk = (n: StructureNode) => {
      if (n.kind === "scene") {
        const sceneType = (n as unknown as { entry_type?: string }).entry_type ?? "scene";
        if (allowed.size === 0 || allowed.has(sceneType)) {
          out.push({ id: n.id, title: n.title, entry_type: sceneType });
        }
      }
      for (const child of n.children ?? []) walk(child);
    };
    walk(node);
    return out;
  }

  $: allScenesUnfiltered = structure ? collectAllScenes(structure.root) : 0;
  $: allScenes = structure ? flattenScenes(structure.root) : [];
  $: filteredScenes = filterByTitle(allScenes, search);

  // Counts the raw scene total irrespective of sub-type filter, so the
  // empty-state copy can distinguish "no scenes in project" from "filter
  // excluded everything." Returns just a number; we don't need the list.
  function collectAllScenes(node: StructureNode | undefined): number {
    if (!node) return 0;
    let count = node.kind === "scene" ? 1 : 0;
    for (const child of node.children ?? []) count += collectAllScenes(child);
    return count;
  }

  function filterByTitle<T extends { title: string }>(items: T[], q: string): T[] {
    if (!q.trim()) return items;
    const lower = q.toLowerCase();
    return items.filter((i) => i.title.toLowerCase().includes(lower));
  }

  // Lore grouped by sub-type, respecting `config.entry_types.lore` filter
  // when set. Empty filter = all sub-types allowed.
  $: loreGroups = (() => {
    const allowed = new Set(config.entry_types?.lore ?? []);
    const visible = loreEntries.filter((entry) =>
      allowed.size === 0 ? true : allowed.has(entry.entry_type),
    );
    const filtered = filterByTitle(visible, search);
    const byType: Record<string, LoreEntrySummary[]> = {};
    for (const entry of filtered) {
      (byType[entry.entry_type] ||= []).push(entry);
    }
    return Object.entries(byType).map(([typeId, entries]) => ({
      typeId,
      typeName: metadataSchema?.entry_types[typeId]?.name ?? typeId,
      entries,
    }));
  })();

  // Snippets are prompts of sub-types where kind=prompt and not abstract
  // and (loosely) snippet-shaped. App.svelte's snippetEntriesFor() filter
  // is more involved; for v1 we just expose all non-abstract prompt
  // entries that match the search.
  $: snippetEntries = filterByTitle(
    promptEntries.filter((p) => {
      const allowed = new Set(config.entry_types?.snippet ?? []);
      return allowed.size === 0 || allowed.has(p.entry_type);
    }),
    search,
  );
  // Counts irrespective of filter, for empty-state copy that distinguishes
  // "no items in project" from "current filter excluded everything."
  $: rawLoreCount = loreEntries.length;
  $: rawSnippetCount = promptEntries.length;

  // Chip text resolution. Show the entry-type's display name from the
  // schema when known; fall back to a sensible singular for the kind.
  // Fixes the inverted-affordance bug where `character` chips read the
  // same as bare `lore` chips because entry_type was missing.
  const KIND_LABEL_SINGULAR: Record<Category | "preset", string> = {
    scene: "Scene",
    lore: "Lore",
    snippet: "Snippet",
    assistant: "Assistant",
    preset: "Preset",
  };

  function chipLabel(ref: ContextPickRef): string {
    if (ref.kind === "preset") return KIND_LABEL_SINGULAR.preset;
    const subType = ref.entry_type && ref.entry_type !== ref.kind ? ref.entry_type : null;
    const displayName = subType ? metadataSchema?.entry_types[subType]?.name : null;
    return displayName ?? subType ?? KIND_LABEL_SINGULAR[ref.kind] ?? ref.kind;
  }

  // True when the picker was opened straight into a leaf category
  // because the config only allows one source. Suppresses the "‹ Back"
  // button — there's no category screen to go back to.
  $: singleSourceMode = allowedKinds.length === 1 && allowedPresets.length === 0;
</script>

<svelte:document on:mousedown={handleDocumentClick} on:keydown={handleKeydown} />

<div class="ctx-picker" class:compact>
  {#if value.length > 0}
    <div class="ctx-chips">
      {#each value as ref (refKey(ref))}
        <span class="ctx-chip" class:preset={ref.kind === "preset"}>
          <small>{chipLabel(ref)}</small>
          <strong>{ref.title}</strong>
          <button
            type="button"
            aria-label="Remove {ref.title}"
            on:click={() => remove(refKey(ref))}
          >×</button>
        </span>
      {/each}
    </div>
  {/if}

  <div class="ctx-picker-anchor">
    <button
      type="button"
      class="ctx-add"
      aria-haspopup="menu"
      aria-expanded={open}
      on:click={toggle}
    >
      + {label}{value.length > 0 ? ` (${value.length})` : ""}
    </button>

    {#if open}
      <div class="ctx-menu" role="menu">
        {#if category === null}
          {#if allowedPresets.length > 0}
            <div class="ctx-group-heading">Presets</div>
            {#each allowedPresets as presetId (presetId)}
              {@const meta = PRESET_META[presetId] ?? { title: presetId, tooltip: "" }}
              <button
                type="button"
                title={meta.tooltip}
                on:click={() => add({ id: presetId, kind: "preset", title: meta.title })}
              >{meta.title}</button>
            {/each}
          {/if}
          {#if allowedKinds.length > 0}
            <div class="ctx-group-heading">Browse</div>
            {#each allowedKinds as kind (kind)}
              <button type="button" on:click={() => openCategory(kind)}>
                {KIND_LABELS[kind]} ›
              </button>
            {/each}
          {/if}
          {#if allowedPresets.length === 0 && allowedKinds.length === 0}
            <p class="ctx-muted">No content sources configured for this picker.</p>
          {/if}
        {:else}
          {#if !singleSourceMode}
            <button type="button" class="ctx-back" on:click={backToCategories}>‹ Back</button>
          {/if}
          <input
            class="ctx-search"
            type="text"
            placeholder="Search…"
            bind:value={search}
          />
          {#if category === "scene"}
            {#each filteredScenes as scene (scene.id)}
              {@const picked = isPicked({ id: scene.id, kind: "scene", title: scene.title })}
              <button
                type="button"
                disabled={picked}
                title={picked ? "Already added" : ""}
                on:click={() => add({ id: scene.id, kind: "scene", title: scene.title, entry_type: scene.entry_type })}
              >{scene.title}</button>
            {/each}
            {#if filteredScenes.length === 0}
              <p class="ctx-muted">
                {#if search}No scenes match "{search}".
                {:else if allScenesUnfiltered > 0}No scenes match this picker's sub-type filter.
                {:else}No scenes in this project yet.
                {/if}
              </p>
            {/if}
          {:else if category === "lore"}
            {#each loreGroups as group (group.typeId)}
              <div class="ctx-group-heading">{group.typeName}</div>
              {#each group.entries as entry (entry.id)}
                {@const picked = isPicked({ id: entry.id, kind: "lore", title: entry.title })}
                <button
                  type="button"
                  disabled={picked}
                  title={picked ? "Already added" : ""}
                  on:click={() => add({ id: entry.id, kind: "lore", title: entry.title, entry_type: entry.entry_type })}
                >{entry.title}</button>
              {/each}
            {/each}
            {#if loreGroups.length === 0}
              <p class="ctx-muted">
                {#if search}No lore entries match "{search}".
                {:else if rawLoreCount > 0}No lore entries match this picker's sub-type filter.
                {:else}No lore entries in this project yet.
                {/if}
              </p>
            {/if}
          {:else if category === "snippet"}
            {#each snippetEntries as snippet (snippet.id)}
              {@const picked = isPicked({ id: snippet.id, kind: "snippet", title: snippet.title })}
              <button
                type="button"
                disabled={picked}
                title={picked ? "Already added" : ""}
                on:click={() => add({ id: snippet.id, kind: "snippet", title: snippet.title, entry_type: snippet.entry_type })}
              >{snippet.title}</button>
            {/each}
            {#if snippetEntries.length === 0}
              <p class="ctx-muted">
                {#if search}No snippets match "{search}".
                {:else if rawSnippetCount > 0}No snippets match this picker's sub-type filter.
                {:else}No snippets in this project yet.
                {/if}
              </p>
            {/if}
          {/if}
        {/if}
      </div>
    {/if}
  </div>
</div>

<style>
  .ctx-picker {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }

  .ctx-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .ctx-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 8px;
    background: #eef2f0;
    border: 1px solid #cbd6d2;
    border-radius: 12px;
    font-size: 12px;
    line-height: 1.2;
  }

  .ctx-chip.preset {
    background: #f4f1e6;
    border-color: #d8d1b9;
  }

  .ctx-chip small {
    color: #65716c;
    text-transform: uppercase;
    font-size: 10px;
    letter-spacing: 0.04em;
  }

  .ctx-chip button {
    border: none;
    background: transparent;
    color: #65716c;
    font-size: 14px;
    line-height: 1;
    padding: 0 2px;
    cursor: pointer;
  }

  .ctx-chip button:hover {
    color: #b04a3f;
  }

  .ctx-picker-anchor {
    position: relative;
    align-self: flex-start;
  }

  .ctx-add {
    padding: 4px 10px;
    border: 1px solid #cbd6d2;
    background: transparent;
    border-radius: 4px;
    font-size: 13px;
    cursor: pointer;
  }

  .ctx-add:hover {
    background: #fafbfa;
  }

  .ctx-menu {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    min-width: 220px;
    max-width: 320px;
    max-height: 360px;
    overflow-y: auto;
    background: #ffffff;
    border: 1px solid #cbd6d2;
    border-radius: 6px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
    padding: 4px;
    z-index: 100;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .ctx-menu button {
    text-align: left;
    padding: 5px 8px;
    border: none;
    background: transparent;
    border-radius: 4px;
    cursor: pointer;
    font-size: 13px;
  }

  .ctx-menu button:hover:not(:disabled) {
    background: #f4f7f5;
  }

  .ctx-menu button:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .ctx-back {
    color: #65716c;
    font-size: 12px !important;
  }

  .ctx-search {
    padding: 4px 8px;
    border: 1px solid #cbd6d2;
    border-radius: 4px;
    font-size: 13px;
    margin: 2px 0;
  }

  .ctx-group-heading {
    padding: 6px 8px 2px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #65716c;
    font-weight: 600;
  }

  .ctx-muted {
    margin: 0;
    padding: 6px 8px;
    color: #65716c;
    font-size: 12px;
  }

  .compact .ctx-add {
    font-size: 12px;
    padding: 3px 8px;
  }
</style>
