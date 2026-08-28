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
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";

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
  // Set when an in-menu navigation (drill/ascend) just changed the level, so the
  // focus action moves focus onto the new first item exactly once. Never set on
  // open — a non-modal menu must not steal focus from its trigger.
  let navPending = $state(false);

  // Re-walk from the root each render, clamping to the deepest prefix that still
  // resolves. If a drilled-into group vanishes from a reactively-updated `nodes`,
  // the fallback level AND the crumb/Back reflect where we actually landed (never
  // a gone group), and a stale suffix can't accumulate on `path`.
  let resolved = $derived.by(() => {
    let current = nodes;
    const valid: string[] = [];
    for (const label of path) {
      const group = current.find((node) => node.label === label && node.children.length > 0);
      if (!group) break;
      valid.push(label);
      current = group.children;
    }
    return { level: current, path: valid };
  });

  function activate(node: MenuNode): void {
    if (node.children.length > 0) {
      path = [...resolved.path, node.label];
      navPending = true;
    } else if (node.entry) {
      onSelect(node.entry);
    }
  }

  function back(): void {
    path = resolved.path.slice(0, -1);
    navPending = true;
  }

  // Escape/ArrowLeft ascend one level while drilled in; at the root they fall
  // through to the Popover (Escape closes it). stopPropagation keeps the Popover's
  // window listener from closing the whole menu when we only meant to go up.
  // ArrowRight mirrors Enter/click on a group item — descend via the same
  // `activate` a click already calls. `node` is only passed for the drill-down
  // items (not the ‹ Back row), so ArrowRight there is a no-op.
  function onItemKeydown(event: KeyboardEvent, node?: MenuNode): void {
    if (event.key === "ArrowRight" && node && node.children.length > 0) {
      event.preventDefault();
      activate(node);
      return;
    }
    if (resolved.path.length === 0) return;
    if (event.key === "Escape" || event.key === "ArrowLeft") {
      event.preventDefault();
      event.stopPropagation();
      back();
    }
  }

  // After a level change, move focus onto the new first item so the menu stays
  // keyboard-operable: activating a group unmounts the focused button, so without
  // this focus would fall to <body> and Enter-to-open / Escape-to-ascend would
  // stop working past the first step. Runs only when a navigation is pending, so
  // it never fires on open or on a background `nodes` refresh.
  function focusOnNav(el: HTMLElement, isFirst: boolean) {
    const apply = (first: boolean): void => {
      if (first && navPending) {
        navPending = false;
        el.focus();
      }
    };
    apply(isFirst);
    return { update: apply };
  }
</script>

{#if resolved.path.length > 0}
  <button type="button" class="pm-back" role="menuitem" onclick={back} onkeydown={onItemKeydown}>
    ‹ Back
  </button>
  <div class="pm-crumb" aria-hidden="true">{resolved.path.join(" / ")}</div>
{/if}
{#each resolved.level as node, i (node.label + (node.entry?.id ?? "·group"))}
  <button
    type="button"
    class="pm-item"
    role="menuitem"
    aria-haspopup={node.children.length > 0 ? "menu" : undefined}
    use:focusOnNav={i === 0}
    onclick={() => activate(node)}
    onkeydown={(event) => onItemKeydown(event, node)}
  >
    <span class="pm-label">{node.label}</span>
    {#if node.children.length > 0}<GroupCaret size="xs" collapsed />{/if}
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
