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
  import type { ContextPickConfig, MetadataSchema } from "./types";

  export let config: ContextPickConfig;
  export let metadataSchema: MetadataSchema | null = null;

  const dispatch = createEventDispatcher<{ change: { config: ContextPickConfig } }>();

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
  };

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

  function emit(patch: Partial<ContextPickConfig>) {
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

  $: hasAnySource =
    (renderedByKind.scene.some((n) => n.state !== "unchecked")) ||
    (renderedByKind.lore.some((n) => n.state !== "unchecked")) ||
    (config.presets ?? []).length > 0;
</script>

<div class="ctx-config">
  <section class="ctx-config-section">
    <header>
      <strong>Pickable content</strong>
      <small>Check what this prompt may attach. Checking a parent enables all descendants.</small>
    </header>
    {#each KINDS as kind (kind.id)}
      <div class="ctx-config-kind">
        <div class="ctx-config-kind-label">{kind.label}</div>
        {#if renderedByKind[kind.id].length === 0}
          <p class="ctx-muted">No {kind.label.toLowerCase()} sub-types defined in this project.</p>
        {:else}
          {#each renderedByKind[kind.id] as item (item.id)}
            <div class="ctx-tree-node" style="--depth: {item.depth}">
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
                  type="checkbox"
                  checked={item.state === "checked"}
                  use:indeterminateBinding={item.state === "indeterminate"}
                  disabled={!item.hasLeaves}
                  on:change={() => toggleNode(kind.id, item.id)}
                />
                <span class="ctx-tree-name">{item.name}</span>
              </label>
            </div>
          {/each}
        {/if}
      </div>
    {/each}
  </section>

  <section class="ctx-config-section">
    <header><strong>Presets</strong></header>
    {#each PRESETS as preset (preset.id)}
      <label class="ctx-config-check">
        <input
          type="checkbox"
          checked={(config.presets ?? []).includes(preset.id)}
          on:change={(e) => togglePreset(preset.id, (e.currentTarget as HTMLInputElement).checked)}
        />
        {preset.label}
        <small class="ctx-config-preset-tip">{preset.tooltip}</small>
      </label>
    {/each}
  </section>

  {#if !hasAnySource}
    <p class="ctx-warn">
      ⚠ Pick at least one source or preset — this picker will be empty at runtime.
    </p>
  {/if}
</div>

<style>
  .ctx-config {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 8px 10px;
    border: 1px dashed #cbd6d2;
    border-radius: 4px;
    background: #fafbfa;
    font-size: 12px;
  }

  .ctx-config-section {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .ctx-config-section > header {
    display: flex;
    flex-direction: column;
    gap: 1px;
    margin-bottom: 2px;
  }

  .ctx-config-section > header strong {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #4d5753;
  }

  .ctx-config-section > header small {
    font-size: 11px;
    color: #65716c;
    line-height: 1.3;
  }

  .ctx-config-kind {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding-top: 4px;
  }

  .ctx-config-kind-label {
    font-weight: 600;
    color: #2a3431;
  }

  .ctx-config-check {
    display: inline-flex;
    align-items: baseline;
    gap: 6px;
    cursor: pointer;
  }

  .ctx-config-preset-tip {
    color: #65716c;
    font-size: 11px;
  }

  .ctx-tree-node {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 4px;
    padding-left: calc(var(--depth, 0) * 18px);
  }

  .ctx-tree-chevron {
    width: 16px;
    height: 16px;
    padding: 0;
    border: none;
    background: transparent;
    color: #65716c;
    font-size: 11px;
    line-height: 1;
    cursor: pointer;
    border-radius: 3px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .ctx-tree-chevron:hover {
    background: #eef2f0;
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
    gap: 6px;
    cursor: pointer;
  }

  .ctx-tree-label.disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  .ctx-tree-abstract {
    color: #65716c;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .ctx-warn {
    margin: 0;
    padding: 6px 8px;
    background: #fff4e6;
    border: 1px solid #f3d9a8;
    border-radius: 4px;
    color: #92560f;
    font-size: 12px;
  }

  .ctx-muted {
    margin: 2px 0;
    padding: 0 4px;
    color: #65716c;
    font-size: 11px;
    font-style: italic;
  }
</style>
