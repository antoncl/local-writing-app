<script context="module" lang="ts">
  import type { PromptEntrySummary } from "@/lib/types";

  type PromptSubtypeNode = { id: string; label: string; children: PromptSubtypeNode[] };
</script>

<script lang="ts">
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { focusedDocumentStore, pinnedKeysStore } from "@/lib/stores/editorFocus";

  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  $: schema = $metadataSchemaStore;
  export let entries: PromptEntrySummary[];
  // Active-row highlight + pin-star read from the editor-focus store, not props (#14 Step 2).
  $: focusedDocument = $focusedDocumentStore;
  $: pinnedKeys = $pinnedKeysStore;
  // Open a prompt entry in an editor pane (App owns the pane set).
  export let onOpenEntry: (entryId: string) => void;
  // Create a new prompt entry of the given concrete sub-type.
  export let onNewEntry: (entryType: string) => void;

  // Per-group collapse — pane-local, not persisted (same as Lore/Assistants).
  let collapsedGroups: Record<string, boolean> = {};

  $: concreteSubtypes = Object.entries(schema?.entry_types ?? {})
    .filter(([id, definition]) => definition.kind === "prompt" && !definition.abstract && id !== "prompt")
    .map(([id, definition]) => ({ id, label: definition.name || id, parent: definition.parent ?? null }));

  // Tree of concrete prompt subtypes — Roleplay nests under Continuation, etc.
  // The pane renders this recursively (each subtype is a group-header NodeRow
  // whose nested slot holds its prompt entries AND its child subtype NodeRows),
  // so the schema hierarchy reads via real nesting in NodeRow's tier panel
  // rather than a depth-padding hack. Tier1/tier2/tier3 backgrounds in NodeRow's
  // scoped CSS handle the visual stepping automatically.
  $: subtypeTree = (() => {
    const byId = new Map<string, PromptSubtypeNode>(
      concreteSubtypes.map((s) => [s.id, { id: s.id, label: s.label, children: [] }]),
    );
    const roots: PromptSubtypeNode[] = [];
    for (const s of concreteSubtypes) {
      const node = byId.get(s.id);
      if (!node) continue;
      const parent = s.parent ? byId.get(s.parent) : undefined;
      if (parent) parent.children.push(node);
      else roots.push(node);
    }
    function sortRecursively(nodes: PromptSubtypeNode[]) {
      nodes.sort((a, b) => a.label.localeCompare(b.label));
      for (const n of nodes) sortRecursively(n.children);
    }
    sortRecursively(roots);
    return roots;
  })();

  function toggleGroup(groupId: string) {
    collapsedGroups = {
      ...collapsedGroups,
      [groupId]: !collapsedGroups[groupId],
    };
  }
</script>

<NodeList isEmpty={subtypeTree.length === 0}>
  {#each subtypeTree as root (root.id)}
    {@render renderSubtype(root)}
  {/each}
  {#snippet whenEmpty()}
    <p class="muted">No prompt sub-types defined yet. Open a prompt entry's Detail Types to create one.</p>
  {/snippet}
</NodeList>

{#snippet renderSubtype(node: PromptSubtypeNode)}
  {@const subtypeEntries = entries.filter((e) => e.entry_type === node.id)}
  {@const userCollapsed = !!collapsedGroups[node.id]}
  {@const hasContent = subtypeEntries.length > 0 || node.children.length > 0}
  {@const isCollapsed = userCollapsed || !hasContent}
  <NodeRow
    groupHeader
    collapsed={isCollapsed}
    title={node.label}
    onClick={() => toggleGroup(node.id)}
  >
    {#snippet leading()}
      <span class:collapsed={isCollapsed} class="lore-group-caret">▾</span>
    {/snippet}
    {#snippet trailing()}
      <span class="group-count-pill">{subtypeEntries.length}</span>
      <button class="pin-button" type="button" on:click|stopPropagation={() => onNewEntry(node.id)}>+ Entry</button>
    {/snippet}
    {#snippet nested()}
      {#each subtypeEntries as entry (entry.id)}
        <NodeRow
          title={entry.title}
          active={focusedDocument?.type === "prompt" && focusedDocument.id === entry.id}
          pinned={pinnedKeys.has(`prompt:${entry.id}`)}
          onClick={() => onOpenEntry(entry.id)}
        />
      {/each}
      {#each node.children as child (child.id)}
        {@render renderSubtype(child)}
      {/each}
    {/snippet}
  </NodeRow>
{/snippet}
