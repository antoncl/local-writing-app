<script lang="ts">
  import { createEventDispatcher } from "svelte";

  export let value: string = "";
  export let knownTags: string[] = [];
  export let ariaLabel: string;
  export let placeholder: string = "Comma-separated values";

  const dispatch = createEventDispatcher<{ change: { value: string } }>();

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
      {#if knownTags.length > 0}
        {#each knownTags as tag}
          <button
            class:active={selectedKeys.has(tag.toLowerCase())}
            type="button"
            on:mousedown|preventDefault
            on:click={() => applyTag(tag)}
          >{tag}</button>
        {/each}
      {:else}
        <span>No known tags yet.</span>
      {/if}
    </div>
  {/if}
</div>
