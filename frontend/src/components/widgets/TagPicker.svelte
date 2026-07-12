<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import type { ScopedTag } from "@/lib/types";
  import { pickerMembership } from "@/lib/utils/pickerSources";

  export let value: string = "";
  export let knownTags: ScopedTag[] = [];
  // The current node's kind + sub-type — used to filter suggestions by tag
  // scope (a tag is suggested where its scope is empty or includes this).
  export let scopeKind: string = "";
  export let scopeEntryType: string = "";
  export let ariaLabel: string;
  export let placeholder: string = "Comma-separated values";

  const dispatch = createEventDispatcher<{ change: { value: string } }>();

  function inScope(tag: ScopedTag): boolean {
    // Tag scopes stay the degenerate type-leaf subset (ADR-0023) — read the
    // legacy {kinds, entryTypes} view of the scope's `sources`.
    const { kinds, entryTypes } = pickerMembership(tag.scope);
    if (kinds.length === 0 && Object.keys(entryTypes).length === 0) return true;
    if (kinds.length && !kinds.includes(scopeKind)) return false;
    const subs = entryTypes[scopeKind];
    if (subs && subs.length && !subs.includes(scopeEntryType)) return false;
    return true;
  }
  $: suggestions = knownTags.filter(inScope);

  let open = false;
  let position: { x: number; y: number; width: number } | null = null;
  let anchorEl: HTMLDivElement | null = null;

  function parseTags(raw: string): string[] {
    return raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  $: selectedKeys = new Set(parseTags(value).map((t) => t.toLowerCase()));

  function toggle(event: MouseEvent) {
    if (open) {
      open = false;
      position = null;
      return;
    }
    const bounds = (anchorEl ?? (event.currentTarget as HTMLElement)).getBoundingClientRect();
    position = {
      x: bounds.left,
      y: bounds.bottom + 4,
      width: Math.min(320, Math.max(220, bounds.width)),
    };
    open = true;
  }

  function handleOutsidePointerdown(event: PointerEvent) {
    if (!open || !anchorEl) return;
    const target = event.target;
    if (target instanceof Node && anchorEl.contains(target)) return;
    // The menu portals to <body> (outside anchorEl), so a pointerdown inside it
    // must not count as "outside" — otherwise it closes before the suggestion's
    // click lands. Query the portaled node the same way its sibling pickers do.
    const menu = document.querySelector(".tag-picker");
    if (menu && target instanceof Node && menu.contains(target)) return;
    open = false;
    position = null;
  }

  // Portal the menu to <body> so its `position: fixed` resolves against the
  // viewport, not a transformed ancestor (the view designer's Svelte Flow pane
  // carries a CSS transform that would otherwise trap it — #225). Mirrors
  // NodePicker; toggle() already captures viewport coords from the anchor rect.
  function portalToBody(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }

  function applyTag(tag: string) {
    const key = tag.toLowerCase();
    const nextTags = parseTags(value).filter((item) => item.toLowerCase() !== key);
    nextTags.push(tag);
    dispatch("change", { value: nextTags.join(", ") });
  }
</script>

<svelte:window on:pointerdown={handleOutsidePointerdown} />

<div class="tag-picker-anchor" bind:this={anchorEl}>
  <div class="tag-field-control">
    <input
      {value}
      {placeholder}
      aria-label={ariaLabel}
      on:input={(event) => dispatch("change", { value: event.currentTarget.value })}
    />
    <button
      class="tag-picker-toggle"
      type="button"
      title="Add known tags"
      on:click={toggle}
    >+</button>
  </div>
  {#if open && position}
    <div
      class="tag-picker"
      style={`left: ${position.x}px; top: ${position.y}px; width: ${position.width}px;`}
      aria-label={`${ariaLabel} known tags`}
      use:portalToBody
    >
      {#if suggestions.length > 0}
        {#each suggestions as tag}
          <button
            class:active={selectedKeys.has(tag.name.toLowerCase())}
            type="button"
            on:mousedown|preventDefault
            on:click={() => applyTag(tag.name)}
          >{tag.name}</button>
        {/each}
      {:else}
        <span>No tags suggested here yet.</span>
      {/if}
    </div>
  {/if}
</div>

<style>
  .tag-picker-anchor {
    position: relative;
  }

  .tag-field-control {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 6px;
    align-items: end;
  }

  .tag-picker-toggle {
    min-width: 32px;
    padding-left: 0;
    padding-right: 0;
    border: 1px dashed var(--border-strong, var(--border-strong));
    border-radius: 8px;
    background: var(--inset);
    color: var(--text-2, var(--text-2));
    font-size: var(--fs-lg);
    line-height: 1;
  }

  .tag-picker-toggle:hover {
    border-color: var(--accent);
    color: var(--accent-strong);
    background: var(--surface);
  }

  .tag-picker {
    position: fixed;
    z-index: 10000;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    max-width: min(360px, calc(100vw - 24px));
    max-height: min(260px, calc(100vh - 24px));
    overflow: auto;
    padding: 8px;
    border: 1px solid var(--divider);
    border-radius: 6px;
    background: var(--surface);
    box-shadow: var(--elev-2);
  }

  .tag-picker button {
    padding: 4px 7px;
    border-radius: 999px;
    font-size: var(--fs-sm);
  }

  .tag-picker button.active {
    border-color: var(--accent);
    color: var(--accent-deep);
    background: var(--accent-soft);
  }

  .tag-picker span {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
</style>
