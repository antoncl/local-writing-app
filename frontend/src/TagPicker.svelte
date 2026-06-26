<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import type { ScopedTag } from "./types";

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
    const scope = tag.scope ?? { kinds: [], entry_types: {} };
    const kinds = scope.kinds ?? [];
    const entryTypes = scope.entry_types ?? {};
    if (kinds.length === 0 && Object.keys(entryTypes).length === 0) return true;
    if (kinds.length && !kinds.includes(scopeKind as never)) return false;
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
    open = false;
    position = null;
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
