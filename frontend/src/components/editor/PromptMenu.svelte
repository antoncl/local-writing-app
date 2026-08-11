<script lang="ts">
  // The drill-down renderer for a prompt submenu tree (#832). Prompt titles encode
  // structure via "/", `buildPromptMenuTree` turns the flat list into groups, and
  // this walks it one level at a time INSIDE the caller's Popover panel: clicking a
  // group swaps this panel's contents for that group's children plus a ‹ Back row;
  // clicking a leaf runs its prompt. In-panel drill-down (not cascading fly-out
  // popovers) is the #832 decision — no second-anchor positioning, no hover-intent
  // timing, works on touch, and Back/ArrowLeft/Escape ascend by keyboard.
  //
  // Content-only, like every Popover child (it carries its own style scope). The
  // caller owns the Popover shell (role="menu", dismiss, Escape-to-close at root).
  import type { MenuNode } from "@/lib/editor-core/promptMenuTree";
  import type { PromptEntrySummary } from "@/lib/types";

  let {
    nodes,
    onSelect,
  }: {
    nodes: MenuNode[];
    onSelect: (entry: PromptEntrySummary) => void;
  } = $props();

  // The groups drilled into, by label. The Popover unmounts its children on close,
  // so this remounts fresh (path = []) on every open — no explicit reset needed.
  let path = $state<string[]>([]);

  // Re-walk from the root each render so a reactive `nodes` change can't strand us
  // on a stale level (if the drilled group vanishes, the walk stops early).
  let level = $derived.by(() => {
    let current = nodes;
    for (const label of path) {
      const group = current.find((node) => node.label === label && node.children.length > 0);
      if (!group) break;
      current = group.children;
    }
    return current;
  });

  function activate(node: MenuNode): void {
    if (node.children.length > 0) path = [...path, node.label];
    else if (node.entry) onSelect(node.entry);
  }

  function back(): void {
    path = path.slice(0, -1);
  }

  // Escape/ArrowLeft ascend one level while drilled in; at the root they fall
  // through to the Popover (Escape closes it). stopPropagation keeps the Popover's
  // window listener from closing the whole menu when we only meant to go up.
  function onItemKeydown(event: KeyboardEvent): void {
    if (path.length === 0) return;
    if (event.key === "Escape" || event.key === "ArrowLeft") {
      event.preventDefault();
      event.stopPropagation();
      back();
    }
  }
</script>

{#if path.length > 0}
  <button type="button" class="pm-back" role="menuitem" onclick={back} onkeydown={onItemKeydown}>
    ‹ Back
  </button>
  <div class="pm-crumb" aria-hidden="true">{path.join(" / ")}</div>
{/if}
{#each level as node (node.label + (node.entry?.id ?? "·group"))}
  <button
    type="button"
    class="pm-item"
    role="menuitem"
    aria-haspopup={node.children.length > 0 ? "menu" : undefined}
    onclick={() => activate(node)}
    onkeydown={onItemKeydown}
  >
    <span class="pm-label">{node.label}</span>
    {#if node.children.length > 0}<span class="pm-caret" aria-hidden="true">›</span>{/if}
  </button>
{/each}

<style>
  .pm-item,
  .pm-back {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 8px 10px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    text-align: left;
    font: inherit;
    font-size: var(--fs-md);
    color: var(--text);
    cursor: pointer;
    white-space: nowrap;
  }
  .pm-item:hover,
  .pm-back:hover {
    background: var(--panel);
  }

  .pm-label {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* The drill-in affordance — a quiet chevron, right-aligned. */
  .pm-caret {
    flex: none;
    color: var(--text-3);
  }

  .pm-back {
    color: var(--text-2);
  }

  /* The trail of groups drilled into — orienting chrome, not interactive. */
  .pm-crumb {
    padding: 2px 10px 4px;
    color: var(--text-3);
    font-size: var(--fs-xs);
  }
</style>
