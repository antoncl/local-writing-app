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

  // Author opt-in: ★ target marking only when config flags it. Surface
  // controlled by the prompt author so template code knows whether
  // `scene` is reliably bound.
  $: allowTargetMarking = config.allow_target_marking === true;

  // ★ target marking: one scene per input may be flagged as the template's
  // `scene` binding (NC-style). Clicking ★ on a scene toggles it; clicking
  // ★ on a different scene moves the mark. Non-scene refs ignore the flag.
  function toggleTarget(ref: ContextPickRef) {
    if (ref.kind !== "scene" || !allowTargetMarking) return;
    const targetKey = refKey(ref);
    const willBeTarget = !ref.target;
    const next = value.map((r) => {
      if (r.kind !== "scene") return r;
      if (refKey(r) === targetKey) return { ...r, target: willBeTarget };
      // Single ★ per input — clear any prior target on other scene refs.
      if (r.target) return { ...r, target: false };
      return r;
    });
    dispatch("change", { value: next });
  }

  function toggle() {
    open = !open;
    if (open) search = "";
  }

  function close() {
    open = false;
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
      // StructureNode uses `type` ("scene" / "act" / "chapter" / "root").
      // An earlier read used `n.kind`, which is always undefined — so
      // the scene list was silently empty. scene_id is the canonical id
      // for the scene itself (the structure node has its own id for the
      // outline position).
      if (n.type === "scene" && n.scene_id) {
        const sceneType = (n as unknown as { entry_type?: string }).entry_type ?? "scene";
        if (allowed.size === 0 || allowed.has(sceneType)) {
          out.push({ id: n.scene_id, title: n.title, entry_type: sceneType });
        }
      }
      for (const child of n.children ?? []) walk(child);
    };
    walk(node);
    return out;
  }

  $: allScenes = structure ? flattenScenes(structure.root) : [];
  $: filteredScenes = filterByTitle(allScenes, search);

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

  // Compute item tag (the small "Scene" / "Character" / "Preset" label
  // shown alongside a result in the unified menu). Mirrors chipLabel
  // for selected items, but for a tree item we have the full ref-shape
  // info ready at render time.
  function itemTag(kind: ContextPickRef["kind"], entryType?: string): string {
    if (kind === "preset") return KIND_LABEL_SINGULAR.preset;
    const sub = entryType && entryType !== kind ? entryType : null;
    const displayName = sub ? metadataSchema?.entry_types[sub]?.name : null;
    return displayName ?? sub ?? KIND_LABEL_SINGULAR[kind] ?? kind;
  }

  // Aggregate visible groups for the unified menu. Each group renders
  // as a collapsible <details> with a header and a flat item list.
  // Groups with no items (after the search filter and config gating)
  // are dropped entirely.
  $: visibleGroups = (() => {
    type Group = { id: string; label: string; items: Array<{ ref: ContextPickRef; tag: string }> };
    const groups: Group[] = [];

    const matchingPresets = allowedPresets.filter((id) => {
      const meta = PRESET_META[id] ?? { title: id, tooltip: "" };
      if (!search.trim()) return true;
      return meta.title.toLowerCase().includes(search.toLowerCase());
    });
    if (matchingPresets.length > 0) {
      groups.push({
        id: "presets",
        label: "Presets",
        items: matchingPresets.map((presetId) => {
          const meta = PRESET_META[presetId] ?? { title: presetId, tooltip: "" };
          return {
            ref: { id: presetId, kind: "preset" as const, title: meta.title },
            tag: itemTag("preset"),
          };
        }),
      });
    }

    if (allowedKinds.includes("scene") && filteredScenes.length > 0) {
      groups.push({
        id: "scenes",
        label: "Scenes",
        items: filteredScenes.map((s) => ({
          ref: { id: s.id, kind: "scene" as const, title: s.title, entry_type: s.entry_type },
          tag: itemTag("scene", s.entry_type),
        })),
      });
    }

    if (allowedKinds.includes("lore")) {
      const loreItems = loreGroups.flatMap((g) =>
        g.entries.map((entry) => ({
          ref: { id: entry.id, kind: "lore" as const, title: entry.title, entry_type: entry.entry_type },
          tag: itemTag("lore", entry.entry_type),
        })),
      );
      if (loreItems.length > 0) {
        groups.push({ id: "lore", label: "Lore", items: loreItems });
      }
    }

    if (allowedKinds.includes("snippet") && snippetEntries.length > 0) {
      groups.push({
        id: "snippets",
        label: "Snippets",
        items: snippetEntries.map((s) => ({
          ref: { id: s.id, kind: "snippet" as const, title: s.title, entry_type: s.entry_type },
          tag: itemTag("snippet", s.entry_type),
        })),
      });
    }

    return groups;
  })();

  $: hasAnyConfigured =
    allowedPresets.length > 0 || allowedKinds.length > 0;
  $: hasAnyResults = visibleGroups.length > 0;
</script>

<svelte:document on:mousedown={handleDocumentClick} on:keydown={handleKeydown} />

<div class="ctx-picker" class:compact>
  {#if value.length > 0}
    <div class="ctx-chips">
      {#each value as ref (refKey(ref))}
        <span class="ctx-chip" class:preset={ref.kind === "preset"} class:target={ref.target}>
          <small>{chipLabel(ref)}</small>
          <strong>{ref.title}</strong>
          {#if ref.kind === "scene" && allowTargetMarking}
            <button
              type="button"
              class="ctx-chip-target"
              aria-pressed={ref.target ?? false}
              aria-label={ref.target ? `Unmark ${ref.title} as target scene` : `Mark ${ref.title} as target scene`}
              title={ref.target ? "★ Target — binds to `scene` in the template. Click to unmark." : "Mark as target — binds to `scene` in the template."}
              on:click={() => toggleTarget(ref)}
            >{ref.target ? "★" : "☆"}</button>
          {/if}
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
        <input
          class="ctx-search"
          type="text"
          placeholder="Search…"
          bind:value={search}
          autofocus
        />
        {#if !hasAnyConfigured}
          <p class="ctx-muted">No content sources configured for this picker.</p>
        {:else if !hasAnyResults}
          <p class="ctx-muted">
            {#if search}
              No matches for "{search}".
            {:else}
              No pickable items in this project yet.
            {/if}
          </p>
        {:else}
          {#each visibleGroups as group (group.id)}
            <details open class="ctx-group">
              <summary>
                {group.label}
                <small>· {group.items.length}</small>
              </summary>
              {#each group.items as item}
                {@const picked = isPicked(item.ref)}
                <button
                  type="button"
                  class="ctx-item"
                  disabled={picked}
                  title={picked ? "Already added" : ""}
                  on:click={() => add(item.ref)}
                >
                  <span class="ctx-item-tag">{item.tag}</span>
                  <span class="ctx-item-title">{item.ref.title}</span>
                </button>
              {/each}
            </details>
          {/each}
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

  .ctx-chip.target {
    border-color: #c79a2a;
    box-shadow: 0 0 0 1px #f0d27a inset;
  }

  .ctx-chip-target {
    border: none;
    background: transparent;
    cursor: pointer;
    padding: 0 2px;
    font-size: 14px;
    color: #b8bfbc;
    line-height: 1;
  }

  .ctx-chip-target:hover {
    color: #c79a2a;
  }

  .ctx-chip-target[aria-pressed="true"] {
    color: #c79a2a;
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

  .ctx-search {
    padding: 4px 8px;
    border: 1px solid #cbd6d2;
    border-radius: 4px;
    font-size: 13px;
    margin: 2px 0 4px;
  }

  .ctx-group {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .ctx-group > summary {
    list-style: none;
    cursor: pointer;
    padding: 4px 8px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #4d5753;
    font-weight: 600;
    user-select: none;
  }

  .ctx-group > summary::-webkit-details-marker {
    display: none;
  }

  .ctx-group > summary::before {
    content: "▾ ";
    display: inline-block;
    width: 12px;
    color: #65716c;
    transition: transform 0.1s;
  }

  .ctx-group:not([open]) > summary::before {
    content: "▸ ";
  }

  .ctx-group > summary small {
    color: #65716c;
    font-weight: 400;
    text-transform: none;
    letter-spacing: 0;
  }

  .ctx-item {
    display: grid !important;
    grid-template-columns: minmax(70px, max-content) 1fr;
    align-items: center;
    gap: 8px;
  }

  .ctx-item-tag {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #65716c;
    background: #eef2f0;
    border-radius: 3px;
    padding: 1px 5px;
    text-align: center;
    line-height: 1.4;
  }

  .ctx-item-title {
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
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
