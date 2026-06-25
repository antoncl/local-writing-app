<script lang="ts">
  // Author-time config editor for a context_pick input.
  //
  // Per [docs/context-picker.md](../../docs/context-picker.md) and the
  // UX-review-driven v2 rewrite:
  //
  // - Pickable content is a hierarchical tree (parent checkbox = check
  //   all descendants; indeterminate when partial). Tree is derived
  //   from the project's metadata schema, so user-added sub-types of
  //   character / place / etc. surface automatically.
  // - Only scene + lore kinds. Snippets are template fragments (you
  //   `{% include %}` them), assistants are personas (you assign them)
  //   — neither is data the model should "know about." Dropped from
  //   the editor entirely.
  // - Positive selection: nothing checked = nothing pickable. Replaces
  //   the "none checked = all allowed" footgun.
  // - The "Allow multiple picks" checkbox lives on the parent input
  //   row alongside Required — gates invocation behaviour, not source
  //   content. This editor no longer owns it.
  // - Validation warning when neither sources nor presets are selected.
  //
  // Implementation note: the tree is rendered FLAT (with depth-based
  // indentation) rather than via recursive snippets. Svelte 5's
  // snippet recursion doesn't reliably re-evaluate `{@const}` derived
  // state in nested calls when the closed-over selection set changes,
  // so leaf checkboxes update but parent indeterminate state goes
  // stale. Flat rendering sidesteps that entirely.

  import { createEventDispatcher } from "svelte";
  import type { NodePickerConfig, MetadataSchema, PromptInputType } from "./types";

  export let config: NodePickerConfig;
  export let metadataSchema: MetadataSchema | null = null;
  // Row-level fields (PR 2). The widget now owns the entire input row
  // when type is context_pick, instead of being slotted inside the
  // generic .prompt-input-grid in NodeEditor.
  export let label: string = "";
  export let name: string = "";
  export let required: boolean = false;

  const dispatch = createEventDispatcher<{
    change: { config: NodePickerConfig };
    labelchange: { value: string };
    namechange: { value: string };
    requiredchange: { value: boolean };
    typechange: { value: PromptInputType };
    remove: Record<string, never>;
  }>();

  // Widget-level collapse state. Local to the component instance — resets
  // when the prompt entry (and therefore this widget) re-mounts. Default
  // to collapsed so a fresh prompt doesn't dump the full picker tree on
  // the author up-front; the row's summary chips communicate intent and
  // the chevron invites expansion when they need to configure it.
  let collapsed = true;
  function toggleWidgetCollapse() {
    collapsed = !collapsed;
  }

  // Match NodeEditor's generic-grid type select. When the user
  // changes type away from context_pick, the parent's {#if} branch
  // unmounts this widget and renders the generic grid for the new type.
  const INPUT_TYPES: { value: PromptInputType; label: string }[] = [
    { value: "text", label: "Text" },
    { value: "long_text", label: "Long Text" },
    { value: "number", label: "Number" },
    { value: "boolean", label: "Boolean" },
    { value: "select", label: "Select" },
    { value: "entity_ref", label: "Entity Reference" },
    { value: "entity_ref_list", label: "Entity Reference List" },
    { value: "context_pick", label: "Context Picker" },
  ];

  type Kind = "scene" | "lore";
  const KINDS: { id: Kind; label: string }[] = [
    { id: "scene", label: "Scenes" },
    { id: "lore", label: "Lore" },
  ];

  const PRESETS: { id: "full_outline" | "full_text"; label: string; tooltip: string }[] = [
    {
      id: "full_outline",
      label: "Full Outline",
      tooltip: "Include the manuscript outline (acts → chapters → scenes with summaries).",
    },
    {
      id: "full_text",
      label: "Full Novel Text",
      tooltip: "Include every scene's prose in manuscript order. Can be large.",
    },
  ];

  type SchemaNode = {
    id: string;
    name: string;
    abstract: boolean;
    children: SchemaNode[];
  };

  type RenderedNode = {
    id: string;
    name: string;
    abstract: boolean;
    depth: number;
    state: "checked" | "indeterminate" | "unchecked";
    hasLeaves: boolean;
    hasChildren: boolean;
    collapsed: boolean;
    pickedCount: number;
    totalLeaves: number;
  };

  type Chip =
    | { kind: "entry"; key: string; entryKind: Kind; entryTypeId: string; label: string }
    | { kind: "preset"; key: string; presetId: "full_outline" | "full_text"; label: string }
    | { kind: "marker"; key: string; label: string };

  // Per-node collapse state. Tracks IDS explicitly collapsed by the
  // user — everything else is expanded by default. Persists for the
  // lifetime of the editor instance (resets when the prompt entry
  // changes). Storage-stable: not persisted to the prompt config.
  let collapsedIds: Set<string> = new Set();

  function toggleCollapse(id: string) {
    const next = new Set(collapsedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    collapsedIds = next;
  }

  // Build the per-kind tree from the project schema. Roots are
  // entry types whose `parent` is null; descendants attach via the
  // parent chain. Abstract types act as containers — they're rendered
  // as checkboxes too, but checking them toggles their concrete
  // descendants (abstracts have no instances so they're not stored).
  function buildTree(schema: MetadataSchema | null, kind: Kind): SchemaNode[] {
    if (!schema) return [];
    type Raw = { id: string; name: string; abstract: boolean; parent: string | null };
    const raw: Raw[] = Object.entries(schema.entry_types ?? {})
      .filter(([, def]) => def.kind === kind)
      .map(([id, def]) => ({
        id,
        name: def.name || id,
        abstract: !!def.abstract,
        parent: def.parent || null,
      }));
    const nodeById = new Map<string, SchemaNode>(
      raw.map((r) => [r.id, { id: r.id, name: r.name, abstract: r.abstract, children: [] }]),
    );
    const roots: SchemaNode[] = [];
    for (const r of raw) {
      const node = nodeById.get(r.id)!;
      if (r.parent && nodeById.has(r.parent)) {
        nodeById.get(r.parent)!.children.push(node);
      } else {
        roots.push(node);
      }
    }
    const sort = (nodes: SchemaNode[]) => {
      nodes.sort((a, b) => {
        if (a.abstract !== b.abstract) return a.abstract ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
      for (const n of nodes) sort(n.children);
    };
    sort(roots);
    return roots;
  }

  function concreteLeaves(node: SchemaNode): string[] {
    if (node.children.length === 0) return node.abstract ? [] : [node.id];
    const out: string[] = [];
    for (const child of node.children) out.push(...concreteLeaves(child));
    return out;
  }

  function nodeState(node: SchemaNode, selection: Set<string>): "checked" | "indeterminate" | "unchecked" {
    const leaves = concreteLeaves(node);
    if (leaves.length === 0) return "unchecked";
    const inSet = leaves.filter((id) => selection.has(id)).length;
    if (inSet === leaves.length) return "checked";
    if (inSet === 0) return "unchecked";
    return "indeterminate";
  }

  function flattenForRender(
    roots: SchemaNode[],
    selection: Set<string>,
    collapsed: Set<string>,
  ): RenderedNode[] {
    const out: RenderedNode[] = [];
    function walk(node: SchemaNode, depth: number) {
      const leaves = concreteLeaves(node);
      const picked = leaves.filter((id) => selection.has(id)).length;
      const hasChildren = node.children.length > 0;
      const isCollapsed = hasChildren && collapsed.has(node.id);
      out.push({
        id: node.id,
        name: node.name,
        abstract: node.abstract,
        depth,
        state: nodeState(node, selection),
        hasLeaves: leaves.length > 0,
        hasChildren,
        collapsed: isCollapsed,
        pickedCount: picked,
        totalLeaves: leaves.length,
      });
      if (!isCollapsed) {
        for (const child of node.children) walk(child, depth + 1);
      }
    }
    for (const root of roots) walk(root, 0);
    return out;
  }

  function selectionFor(kind: Kind): Set<string> {
    const explicit = config.entry_types?.[kind];
    if (explicit && explicit.length > 0) return new Set(explicit);
    // Legacy fallback: a config with `kinds` set but no `entry_types[kind]`
    // historically meant "all sub-types of that kind allowed" at runtime.
    // Reflect that as "all concrete leaves checked" in the editor so the
    // displayed selection matches the runtime behaviour. The first toggle
    // promotes the config to explicit positive selection.
    if (config.kinds?.includes(kind)) {
      return new Set(trees[kind].flatMap((root) => concreteLeaves(root)));
    }
    return new Set();
  }

  function nodeById(kind: Kind, id: string): SchemaNode | undefined {
    function search(node: SchemaNode): SchemaNode | undefined {
      if (node.id === id) return node;
      for (const child of node.children) {
        const hit = search(child);
        if (hit) return hit;
      }
      return undefined;
    }
    for (const root of trees[kind]) {
      const hit = search(root);
      if (hit) return hit;
    }
    return undefined;
  }

  function toggleNode(kind: Kind, id: string) {
    const node = nodeById(kind, id);
    if (!node) return;
    const current = selectionFor(kind);
    const next = new Set(current);
    const leaves = concreteLeaves(node);
    if (leaves.length === 0) return;
    const state = nodeState(node, current);
    if (state === "checked") {
      for (const leaf of leaves) next.delete(leaf);
    } else {
      for (const leaf of leaves) next.add(leaf);
    }
    writeSelection(kind, next);
  }

  function writeSelection(kind: Kind, next: Set<string>) {
    const nextEntryTypes: Record<string, string[]> = { ...(config.entry_types ?? {}) };
    const nextKinds = new Set(config.kinds ?? []);
    if (next.size === 0) {
      delete nextEntryTypes[kind];
      nextKinds.delete(kind);
    } else {
      nextEntryTypes[kind] = Array.from(next).sort();
      nextKinds.add(kind);
    }
    emit({ entry_types: nextEntryTypes, kinds: Array.from(nextKinds) });
  }

  function togglePreset(id: "full_outline" | "full_text", checked: boolean) {
    const next = new Set(config.presets ?? []);
    if (checked) next.add(id);
    else next.delete(id);
    emit({ presets: Array.from(next) });
  }

  function toggleAllowTargetMarking(checked: boolean) {
    emit({ allow_target_marking: checked || undefined });
  }

  // Chip removal — single source of truth: route through the same writers
  // the tree / preset / scene-binding controls already use. The chip band
  // is a projection of config state, not a parallel store.
  function removeEntryChip(entryKind: Kind, entryTypeId: string) {
    const current = selectionFor(entryKind);
    const next = new Set(current);
    next.delete(entryTypeId);
    writeSelection(entryKind, next);
  }

  function emit(patch: Partial<NodePickerConfig>) {
    dispatch("change", { config: { ...config, ...patch } });
  }

  // Imperative indeterminate setter — Svelte's `indeterminate={...}`
  // attribute binding has been observed to go stale when the same
  // input element is reused across re-renders and only the
  // indeterminate property changes (the `checked` attribute stays
  // false either way). `use:` runs on every reactive update and
  // forces the DOM property in lock-step.
  function indeterminateBinding(node: HTMLInputElement, value: boolean) {
    node.indeterminate = value;
    return {
      update(next: boolean) {
        node.indeterminate = next;
      },
    };
  }

  // Schema-derived trees: stable across config edits.
  $: trees = {
    scene: buildTree(metadataSchema, "scene"),
    lore: buildTree(metadataSchema, "lore"),
  };
  // Pre-computed render lists per kind, including each node's checkbox
  // state. The references to `config` and `collapsedIds` here are
  // critical — Svelte 5's legacy `$:` tracking only sees variables
  // read directly in the expression body, not inside function calls.
  // Without explicit references, `selectionFor(...)` reading config
  // from closure wouldn't trigger this block on config changes, and
  // the tree would go stale (same trap as activePromptTitle hit
  // earlier — see [[feedback-svelte5-reactivity-traps]]).
  $: renderedByKind = ((_config, _collapsed) => ({
    scene: flattenForRender(trees.scene, selectionFor("scene"), _collapsed),
    lore: flattenForRender(trees.lore, selectionFor("lore"), _collapsed),
  }))(config, collapsedIds);

  // Per-kind picked-leaf totals (for the kind-bar count).
  $: pickedCountByKind = ((_config) => ({
    scene: selectionFor("scene").size,
    lore: selectionFor("lore").size,
  }))(config);

  // Chip projection — same Svelte 5 closure trap caveat applies; pass
  // config explicitly to make tracking visible to `$:`.
  $: chips = ((_config) => {
    const out: Chip[] = [];
    for (const { id: kind } of KINDS) {
      const ids = _config.entry_types?.[kind] ?? [];
      for (const id of ids) {
        const node = nodeById(kind, id);
        if (!node) continue;
        out.push({
          kind: "entry",
          key: `${kind}:${id}`,
          entryKind: kind,
          entryTypeId: id,
          label: node.name,
        });
      }
    }
    for (const preset of PRESETS) {
      if ((_config.presets ?? []).includes(preset.id)) {
        out.push({
          kind: "preset",
          key: `preset:${preset.id}`,
          presetId: preset.id,
          label: preset.label,
        });
      }
    }
    if (_config.allow_target_marking) {
      out.push({ kind: "marker", key: "marker", label: "marks scene" });
    }
    return out;
  })(config);

  $: hasAnySource =
    (renderedByKind.scene.some((n) => n.state !== "unchecked")) ||
    (renderedByKind.lore.some((n) => n.state !== "unchecked")) ||
    (config.presets ?? []).length > 0;

  // Only surface the ★-marking control when scenes are actually pickable —
  // marking is scene-only; showing it for lore-only inputs would be noise.
  $: scenesPickable = renderedByKind.scene.some((n) => n.state !== "unchecked");

  // Collapsed-state pill strip. Aggregates by kind rather than listing
  // each entry type — gives "Scenes · 2" instead of "Chapter · Scene".
  type CollapsedChip =
    | { key: string; kind: "count"; label: string }
    | { key: string; kind: "preset"; label: string }
    | { key: string; kind: "marker"; label: string };

  $: collapsedChips = ((_config, _pickedByKind) => {
    const out: CollapsedChip[] = [];
    for (const { id: k, label: kLabel } of KINDS) {
      const n = _pickedByKind[k];
      if (n > 0) out.push({ key: `count:${k}`, kind: "count", label: `${kLabel} · ${n}` });
    }
    for (const preset of PRESETS) {
      if ((_config.presets ?? []).includes(preset.id)) {
        out.push({ key: `preset:${preset.id}`, kind: "preset", label: preset.label });
      }
    }
    if (_config.allow_target_marking) {
      out.push({ key: "marker", kind: "marker", label: "marks scene" });
    }
    return out;
  })(config, pickedCountByKind);
</script>

<div class="ctx-config" class:collapsed>
  <div class="ctx-row-header">
    <button
      type="button"
      class="ctx-row-chevron"
      aria-label={collapsed ? "Expand context picker" : "Collapse context picker"}
      aria-expanded={!collapsed}
      on:click={toggleWidgetCollapse}
    >{collapsed ? "▸" : "▾"}</button>

    <div class="ctx-row-id-stack">
      <input
        class="ctx-row-label-input"
        value={label}
        placeholder="Reference scenes"
        aria-label="Input label"
        on:input={(e) => dispatch("labelchange", { value: (e.currentTarget as HTMLInputElement).value })}
      />
      <div class="ctx-row-accessor-row">
        <input
          class="ctx-row-name-input"
          value={name}
          placeholder="reference_scenes"
          aria-label="Input id"
          on:input={(e) => dispatch("namechange", { value: (e.currentTarget as HTMLInputElement).value })}
        />
        {#if name}
          <code class="ctx-row-accessor">&lbrace;&lbrace; input.{name} &rbrace;&rbrace;</code>
        {/if}
      </div>
    </div>

    <span class="ctx-row-type">
      <select
        class="ctx-row-type-select"
        value="context_pick"
        aria-label="Input type"
        on:change={(e) => dispatch("typechange", { value: (e.currentTarget as HTMLSelectElement).value as PromptInputType })}
      >
        {#each INPUT_TYPES as t (t.value)}
          <option value={t.value}>{t.label}</option>
        {/each}
      </select>
    </span>

    <div class="ctx-row-toggles">
      <label class="ctx-row-toggle">
        <input
          class="ctx-check"
          type="checkbox"
          checked={required}
          on:change={(e) => dispatch("requiredchange", { value: (e.currentTarget as HTMLInputElement).checked })}
        />
        <span>Required</span>
      </label>
      <label class="ctx-row-toggle">
        <input
          class="ctx-check"
          type="checkbox"
          checked={config.multiple !== false}
          on:change={(e) => emit({ multiple: (e.currentTarget as HTMLInputElement).checked })}
        />
        <span>Multiple</span>
      </label>
      <button
        type="button"
        class="ctx-row-remove"
        aria-label="Remove input"
        title="Remove input"
        on:click={() => dispatch("remove", {})}
      >×</button>
    </div>
  </div>

  {#if collapsed}
    <div class="ctx-collapsed-strip">
      {#if collapsedChips.length === 0}
        <span class="ctx-collapsed-warn">
          <span aria-hidden="true">⚠</span>
          Nothing pickable yet
        </span>
      {:else}
        {#each collapsedChips as chip (chip.key)}
          {#if chip.kind === "count"}
            <span class="ctx-collapsed-pill">
              <span class="ctx-collapsed-dot" aria-hidden="true"></span>
              {chip.label}
            </span>
          {:else if chip.kind === "preset"}
            <span class="ctx-collapsed-pill">{chip.label}</span>
          {:else}
            <span class="ctx-collapsed-pill">
              <span class="ctx-collapsed-star" aria-hidden="true">★</span>
              {chip.label}
            </span>
          {/if}
        {/each}
      {/if}
    </div>
  {:else}
    <div class="ctx-body">
  {#if chips.length > 0}
    <section class="ctx-section">
      <header class="ctx-section-label">Attaches at runtime</header>
      <div class="ctx-chips">
        {#each chips as chip (chip.key)}
          {#if chip.kind === "entry"}
            <span class="ctx-chip">
              <span class="ctx-chip-dot" aria-hidden="true"></span>
              <span class="ctx-chip-label">{chip.label}</span>
              <button
                type="button"
                class="ctx-chip-remove"
                aria-label={`Remove ${chip.label}`}
                on:click={() => removeEntryChip(chip.entryKind, chip.entryTypeId)}
              >✕</button>
            </span>
          {:else if chip.kind === "preset"}
            <span class="ctx-chip ctx-chip-preset">
              <span class="ctx-chip-label">{chip.label}</span>
              <button
                type="button"
                class="ctx-chip-remove"
                aria-label={`Remove ${chip.label}`}
                on:click={() => togglePreset(chip.presetId, false)}
              >✕</button>
            </span>
          {:else}
            <span class="ctx-chip ctx-chip-marker">
              <span class="ctx-chip-star" aria-hidden="true">★</span>
              <span class="ctx-chip-label">{chip.label}</span>
              <button
                type="button"
                class="ctx-chip-remove"
                aria-label="Disable scene marking"
                on:click={() => toggleAllowTargetMarking(false)}
              >✕</button>
            </span>
          {/if}
        {/each}
      </div>
    </section>
  {/if}

  <section class="ctx-section">
    <header class="ctx-section-label">Pickable content</header>
    <div class="ctx-tree-frame">
      {#each KINDS as kind, kindIdx (kind.id)}
        <div class="ctx-tree-kind-bar" class:first={kindIdx === 0}>
          <span class="ctx-tree-kind-label">{kind.label}</span>
          <span class="ctx-tree-kind-count">
            {pickedCountByKind[kind.id] === 0 ? "none" : `${pickedCountByKind[kind.id]} picked`}
          </span>
        </div>
        {#if renderedByKind[kind.id].length === 0}
          <p class="ctx-muted">No {kind.label.toLowerCase()} sub-types defined in this project.</p>
        {:else}
          <div class="ctx-tree-rows">
            {#each renderedByKind[kind.id] as item (item.id)}
              <div class="ctx-tree-row" style="--depth: {item.depth}">
                {#if item.hasChildren}
                  <button
                    type="button"
                    class="ctx-tree-chevron"
                    aria-label={item.collapsed ? `Expand ${item.name}` : `Collapse ${item.name}`}
                    aria-expanded={!item.collapsed}
                    on:click={() => toggleCollapse(item.id)}
                  >{item.collapsed ? "▸" : "▾"}</button>
                {:else}
                  <span class="ctx-tree-chevron ctx-tree-chevron-leaf" aria-hidden="true"></span>
                {/if}
                <label class="ctx-tree-label" class:disabled={!item.hasLeaves}>
                  <input
                    class="ctx-check"
                    type="checkbox"
                    checked={item.state === "checked"}
                    use:indeterminateBinding={item.state === "indeterminate"}
                    disabled={!item.hasLeaves}
                    on:change={() => toggleNode(kind.id, item.id)}
                  />
                  <span class="ctx-tree-name" class:root={item.depth === 0}>{item.name}</span>
                </label>
                {#if item.state === "indeterminate" && item.hasChildren}
                  <span class="ctx-tree-partial-count">{item.pickedCount} of {item.totalLeaves}</span>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      {/each}
    </div>
  </section>

  <section class="ctx-section">
    <header class="ctx-section-label">Whole-document presets</header>
    <div class="ctx-preset-pills">
      {#each PRESETS as preset (preset.id)}
        {@const isOn = (config.presets ?? []).includes(preset.id)}
        <label class="ctx-preset-pill" class:active={isOn} title={preset.tooltip}>
          <input
            class="ctx-preset-pill-input"
            type="checkbox"
            checked={isOn}
            on:change={(e) => togglePreset(preset.id, (e.currentTarget as HTMLInputElement).checked)}
          />
          <span class="ctx-preset-pill-check" aria-hidden="true"></span>
          <span class="ctx-preset-pill-label">{preset.label}</span>
        </label>
      {/each}
    </div>
  </section>

  {#if scenesPickable}
    <section class="ctx-section">
      <header class="ctx-section-label">Scene binding</header>
      <div class="ctx-scene-binding">
        <span class="ctx-scene-binding-icon" aria-hidden="true">★</span>
        <div class="ctx-scene-binding-body">
          <label class="ctx-scene-binding-toggle">
            <input
              class="ctx-check"
              type="checkbox"
              checked={config.allow_target_marking === true}
              on:change={(e) => toggleAllowTargetMarking((e.currentTarget as HTMLInputElement).checked)}
            />
            <span class="ctx-scene-binding-title">Let the writer mark a primary scene</span>
          </label>
          <p class="ctx-scene-binding-help">
            At runtime the picker shows a ★ on each picked scene. The one the writer marks fills
            the template's <code>scene</code> variable — the rest stay available on
            <code>{`{{ input.<id> }}`}</code>, and the marked one wins over any caller-supplied target.
          </p>
        </div>
      </div>
    </section>
  {/if}

  {#if !hasAnySource}
    <p class="ctx-warn">
      <span class="ctx-warn-icon" aria-hidden="true">⚠</span>
      <span>
        Nothing is pickable yet — check at least one type or turn on a preset, or this picker
        shows up empty at runtime.
      </span>
    </p>
  {/if}
    </div>
  {/if}
</div>

<style>
  .ctx-config {
    /* Light theme tokens. Dark set lives in the [data-theme=dark]
       override below so a future toggle in a parent only has to flip
       the attribute — no code changes here. */
    --ctx-board: #e7eae7;
    --ctx-surface: #ffffff;
    --ctx-panel: #f7faf8;
    --ctx-panel-2: #eef3f0;
    --ctx-inset: #f3f6f4;
    --ctx-border: #cdd8d3;
    --ctx-border-strong: #b4c2bc;
    --ctx-text: #28332f;
    --ctx-text-2: #4d5753;
    --ctx-text-3: #6c7872;
    --ctx-accent: #3f7d68;
    --ctx-accent-strong: #356b59;
    --ctx-accent-soft: #e2efe9;
    --ctx-warn-bg: #fff4e6;
    --ctx-warn-border: #f0d29a;
    --ctx-warn-text: #8a520d;
    --ctx-star: #b07d1e;
    --ctx-shadow: rgba(40, 60, 52, 0.08);

    display: flex;
    flex-direction: column;
    border: 1px solid var(--ctx-border);
    border-radius: 9px;
    background: var(--ctx-surface);
    box-shadow: 0 1px 3px var(--ctx-shadow);
    color: var(--ctx-text);
    font-size: 12px;
    overflow: hidden;
  }

  .ctx-body {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 14px 14px 16px;
  }

  :global([data-theme="dark"]) .ctx-config {
    --ctx-board: #0e1613;
    --ctx-surface: #18211d;
    --ctx-panel: #141c18;
    --ctx-panel-2: #1e2823;
    --ctx-inset: #1b2521;
    --ctx-border: #324039;
    --ctx-border-strong: #41534a;
    --ctx-text: #e3e9e5;
    --ctx-text-2: #b4c0ba;
    --ctx-text-3: #869189;
    --ctx-accent: #5ea585;
    --ctx-accent-strong: #7cc0a1;
    --ctx-accent-soft: #22332c;
    --ctx-warn-bg: #2c2414;
    --ctx-warn-border: #5a4a24;
    --ctx-warn-text: #e6c084;
    --ctx-star: #d6a946;
    --ctx-shadow: rgba(0, 0, 0, 0.45);
  }

  /* --- Row header (owns the full input row, PR 2) ----------------- */

  .ctx-row-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    background: var(--ctx-panel-2);
    border-bottom: 1px solid var(--ctx-border);
    flex-wrap: wrap;
  }

  .ctx-config.collapsed .ctx-row-header {
    border-bottom: none;
  }

  .ctx-row-chevron {
    appearance: none;
    width: 18px;
    height: 18px;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--ctx-accent);
    font-size: 11px;
    line-height: 1;
    cursor: pointer;
    border-radius: 4px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: none;
  }

  .ctx-row-chevron:hover {
    background: var(--ctx-inset);
  }

  .ctx-row-id-stack {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    flex: 1 1 200px;
  }

  .ctx-row-label-input {
    appearance: none;
    border: 1px solid transparent;
    background: transparent;
    padding: 2px 6px;
    margin: -2px -6px;
    font-size: 13.5px;
    font-weight: 600;
    color: var(--ctx-text);
    font-family: inherit;
    border-radius: 4px;
    min-width: 0;
    width: 100%;
  }

  .ctx-row-label-input::placeholder {
    color: var(--ctx-text-3);
    font-weight: 500;
  }

  .ctx-row-label-input:hover {
    background: var(--ctx-surface);
    border-color: var(--ctx-border);
  }

  .ctx-row-label-input:focus {
    outline: none;
    background: var(--ctx-surface);
    border-color: var(--ctx-accent);
  }

  .ctx-row-accessor-row {
    display: flex;
    align-items: baseline;
    gap: 8px;
    min-width: 0;
  }

  .ctx-row-name-input {
    appearance: none;
    border: 1px solid transparent;
    background: transparent;
    padding: 1px 5px;
    margin: -1px -5px;
    font-size: 11px;
    color: var(--ctx-text-3);
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    border-radius: 4px;
    min-width: 0;
    flex: 0 1 140px;
  }

  .ctx-row-name-input::placeholder {
    color: var(--ctx-text-3);
    opacity: 0.6;
  }

  .ctx-row-name-input:hover {
    background: var(--ctx-surface);
    border-color: var(--ctx-border);
  }

  .ctx-row-name-input:focus {
    outline: none;
    background: var(--ctx-surface);
    border-color: var(--ctx-accent);
    color: var(--ctx-text-2);
  }

  .ctx-row-accessor {
    font-size: 11px;
    color: var(--ctx-text-3);
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    background: transparent;
    padding: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .ctx-row-type {
    flex: none;
    position: relative;
    display: inline-flex;
  }

  .ctx-row-type-select {
    appearance: none;
    -webkit-appearance: none;
    border: 1px solid var(--ctx-accent);
    background: var(--ctx-accent-soft);
    color: var(--ctx-accent-strong);
    font-size: 10.5px;
    font-weight: 600;
    text-transform: none;
    letter-spacing: 0;
    padding: 3px 22px 3px 10px;
    border-radius: 999px;
    cursor: pointer;
    font-family: inherit;
    line-height: 1.4;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 6'><path d='M1 1 L5 5 L9 1' fill='none' stroke='%23356b59' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/></svg>");
    background-repeat: no-repeat;
    background-position: right 8px center;
    background-size: 8px 5px;
  }

  .ctx-row-type-select:focus-visible {
    outline: 2px solid var(--ctx-accent);
    outline-offset: 1px;
  }

  .ctx-row-toggles {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 12px;
    flex: none;
  }

  .ctx-row-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    cursor: pointer;
    font-size: 11.5px;
    color: var(--ctx-text-2);
    line-height: 1;
  }

  .ctx-row-remove {
    appearance: none;
    background: transparent;
    border: none;
    color: var(--ctx-text-3);
    font-size: 18px;
    line-height: 1;
    padding: 0 4px;
    cursor: pointer;
    border-radius: 4px;
  }

  .ctx-row-remove:hover {
    background: var(--ctx-inset);
    color: var(--ctx-text);
  }

  /* --- Collapsed strip --------------------------------------------- */

  .ctx-collapsed-strip {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: 8px 14px 12px;
    align-items: center;
  }

  .ctx-collapsed-warn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px;
    border-radius: 999px;
    background: var(--ctx-warn-bg);
    border: 1px solid var(--ctx-warn-border);
    color: var(--ctx-warn-text);
    font-size: 11.5px;
    line-height: 1.2;
  }

  .ctx-collapsed-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 9px;
    border-radius: 999px;
    background: var(--ctx-inset);
    border: 1px solid var(--ctx-border);
    font-size: 11.5px;
    color: var(--ctx-text-2);
    line-height: 1.2;
  }

  .ctx-collapsed-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--ctx-accent);
    flex: none;
  }

  .ctx-collapsed-star {
    color: var(--ctx-star);
    font-size: 11px;
    line-height: 1;
  }

  .ctx-section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .ctx-section-label {
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ctx-text-3);
  }

  /* --- Custom checkbox (used in tree + scene-binding) -------------- */

  .ctx-check {
    appearance: none;
    -webkit-appearance: none;
    margin: 0;
    width: 16px;
    height: 16px;
    flex: none;
    border: 1.5px solid var(--ctx-border-strong);
    border-radius: 5px;
    background: var(--ctx-surface);
    cursor: pointer;
    display: inline-block;
    position: relative;
    transition: background-color 80ms linear, border-color 80ms linear;
  }

  .ctx-check:hover:not(:disabled) {
    border-color: var(--ctx-accent);
  }

  .ctx-check:checked {
    background-color: var(--ctx-accent);
    border-color: var(--ctx-accent);
  }

  .ctx-check:checked::after {
    content: "";
    position: absolute;
    inset: 0;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'><path d='M2.5 6.2 L5 8.5 L9.5 3.8' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg>");
    background-repeat: no-repeat;
    background-position: center;
    background-size: 12px 12px;
  }

  .ctx-check:indeterminate {
    background-color: var(--ctx-accent-soft);
    border-color: var(--ctx-accent);
  }

  .ctx-check:indeterminate::after {
    content: "";
    position: absolute;
    left: 3px;
    right: 3px;
    top: 50%;
    height: 2px;
    margin-top: -1px;
    background: var(--ctx-accent);
    border-radius: 1px;
  }

  .ctx-check:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  /* --- Chip summary band ------------------------------------------- */

  .ctx-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
  }

  .ctx-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 4px 4px 10px;
    border-radius: 999px;
    background: var(--ctx-surface);
    border: 1px solid var(--ctx-border);
    font-size: 12px;
    color: var(--ctx-text);
    line-height: 1;
  }

  .ctx-chip-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--ctx-accent);
    flex: none;
  }

  .ctx-chip-star {
    color: var(--ctx-star);
    font-size: 12px;
    line-height: 1;
  }

  .ctx-chip-label {
    line-height: 1.2;
  }

  .ctx-chip-remove {
    appearance: none;
    background: transparent;
    border: none;
    color: var(--ctx-text-3);
    font-size: 11px;
    cursor: pointer;
    padding: 2px 5px;
    border-radius: 999px;
    line-height: 1;
  }

  .ctx-chip-remove:hover {
    background: var(--ctx-panel-2);
    color: var(--ctx-text);
  }

  .ctx-chip-preset {
    background: var(--ctx-accent-soft);
    border-color: var(--ctx-accent);
    color: var(--ctx-accent-strong);
    font-weight: 500;
  }

  .ctx-chip-preset .ctx-chip-remove {
    color: var(--ctx-accent-strong);
  }

  .ctx-chip-preset .ctx-chip-remove:hover {
    background: rgba(53, 107, 89, 0.12);
  }

  /* --- Tree frame -------------------------------------------------- */

  .ctx-tree-frame {
    border: 1px solid var(--ctx-border);
    border-radius: 9px;
    overflow: hidden;
    background: var(--ctx-surface);
  }

  .ctx-tree-kind-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 7px 12px;
    background: var(--ctx-panel-2);
    border-top: 1px solid var(--ctx-border);
    border-bottom: 1px solid var(--ctx-border);
  }

  .ctx-tree-kind-bar.first {
    border-top: none;
  }

  .ctx-tree-kind-label {
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--ctx-text-2);
  }

  .ctx-tree-kind-count {
    font-size: 10.5px;
    color: var(--ctx-text-3);
  }

  .ctx-tree-rows {
    padding: 4px;
    display: flex;
    flex-direction: column;
  }

  .ctx-tree-row {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
    min-height: 30px;
    padding: 0 8px;
    padding-left: calc(8px + var(--depth, 0) * 22px);
    border-radius: 6px;
  }

  .ctx-tree-row:hover {
    background: var(--ctx-panel-2);
  }

  .ctx-tree-chevron {
    width: 15px;
    height: 16px;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--ctx-text-3);
    font-size: 10px;
    line-height: 1;
    cursor: pointer;
    border-radius: 3px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: none;
  }

  .ctx-tree-chevron:hover {
    background: var(--ctx-inset);
  }

  .ctx-tree-chevron-leaf {
    cursor: default;
  }

  .ctx-tree-chevron-leaf:hover {
    background: transparent;
  }

  .ctx-tree-label {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    flex: 1;
    min-width: 0;
  }

  .ctx-tree-label.disabled {
    cursor: not-allowed;
    opacity: 0.6;
  }

  .ctx-tree-name {
    font-size: 12.5px;
    color: var(--ctx-text);
  }

  .ctx-tree-name.root {
    font-weight: 600;
  }

  .ctx-tree-partial-count {
    font-size: 10.5px;
    color: var(--ctx-text-3);
    flex: none;
  }

  /* --- Preset pills ------------------------------------------------ */

  .ctx-preset-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .ctx-preset-pill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 7px 13px;
    border-radius: 999px;
    border: 1.5px solid var(--ctx-border);
    background: var(--ctx-surface);
    font-size: 12.5px;
    color: var(--ctx-text-2);
    cursor: pointer;
    line-height: 1;
    transition: border-color 80ms linear, background-color 80ms linear, color 80ms linear;
  }

  .ctx-preset-pill:hover {
    border-color: var(--ctx-border-strong);
  }

  .ctx-preset-pill.active {
    border-color: var(--ctx-accent);
    background: var(--ctx-accent-soft);
    color: var(--ctx-text);
  }

  .ctx-preset-pill-input {
    /* Visually hidden but focusable so a11y/keyboard still works. */
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  .ctx-preset-pill-check {
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1.5px solid var(--ctx-border-strong);
    background: var(--ctx-surface);
    flex: none;
    position: relative;
  }

  .ctx-preset-pill.active .ctx-preset-pill-check {
    background: var(--ctx-accent);
    border-color: var(--ctx-accent);
  }

  .ctx-preset-pill.active .ctx-preset-pill-check::after {
    content: "";
    position: absolute;
    inset: 0;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'><path d='M2.5 6.2 L5 8.5 L9.5 3.8' fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/></svg>");
    background-repeat: no-repeat;
    background-position: center;
    background-size: 11px 11px;
  }

  .ctx-preset-pill-input:focus-visible + .ctx-preset-pill-check {
    box-shadow: 0 0 0 2px var(--ctx-accent-soft);
  }

  .ctx-preset-pill-label {
    line-height: 1.2;
  }

  /* --- Scene binding block ----------------------------------------- */

  .ctx-scene-binding {
    border: 1px solid var(--ctx-accent);
    border-radius: 10px;
    background: var(--ctx-accent-soft);
    padding: 13px;
    display: flex;
    align-items: flex-start;
    gap: 12px;
  }

  .ctx-scene-binding-icon {
    width: 26px;
    height: 26px;
    flex: none;
    border-radius: 7px;
    background: var(--ctx-surface);
    color: var(--ctx-star);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 15px;
    line-height: 1;
  }

  .ctx-scene-binding-body {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .ctx-scene-binding-toggle {
    display: inline-flex;
    align-items: center;
    gap: 9px;
    cursor: pointer;
  }

  .ctx-scene-binding-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--ctx-text);
  }

  .ctx-scene-binding-help {
    margin: 0;
    font-size: 12px;
    color: var(--ctx-text-2);
    line-height: 1.45;
  }

  .ctx-scene-binding-help code {
    font-size: 11px;
    background: var(--ctx-surface);
    padding: 1px 4px;
    border-radius: 4px;
  }

  /* --- Warn / muted ------------------------------------------------ */

  .ctx-warn {
    display: flex;
    gap: 10px;
    align-items: flex-start;
    margin: 0;
    padding: 11px 13px;
    border-radius: 9px;
    background: var(--ctx-warn-bg);
    border: 1px solid var(--ctx-warn-border);
    color: var(--ctx-warn-text);
    font-size: 12.5px;
    line-height: 1.45;
  }

  .ctx-warn-icon {
    font-size: 15px;
    line-height: 1.2;
    flex: none;
  }

  .ctx-muted {
    margin: 4px 8px 6px;
    color: var(--ctx-text-3);
    font-size: 11px;
    font-style: italic;
  }
</style>
