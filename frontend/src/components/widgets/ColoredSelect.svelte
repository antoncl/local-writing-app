<script lang="ts">
  // Custom dropdown that mirrors `<select>` but renders each option with
  // its swatch color (when set). Selected value displays as a tinted pill.
  // Used for fields like `status` so completeness is visible at a glance
  // in the metadata pane and (later) the scene tree row.
  //
  // Falls back to the neutral chip when an option has no color, so this
  // widget is safe to use even when only SOME options are colored.

  import { getSwatch } from "@/lib/utils/colors";
  import type { SelectOption } from "@/lib/types";

  export let value: string = "";
  export let options: SelectOption[] = [];
  // When true, the trigger renders a small placeholder when value is "".
  export let allowBlank: boolean = true;
  export let placeholder: string = "(none)";
  export let ariaLabel: string = "";
  export let onChange: ((value: string) => void) | undefined = undefined;
  // Read-only display (#64): the trigger pill renders identically (dot +
  // label + tint) but is inert — no popover, no hover affordance, no caret.
  export let readOnly: boolean = false;

  let open = false;
  let anchor: HTMLButtonElement | undefined;
  // Popover is fixed-positioned (computed from the anchor) so it escapes the
  // metadata rail's overflow clipping. Mirrors TagPicker.
  let menuPos: { x: number; y: number; width: number } | null = null;

  $: current = options.find((o) => o.value === value) ?? null;
  // Resolve the swatch hex when the selected option carries a color id.
  $: currentSwatch = current?.color ? getSwatch(current.color) : null;
  // Only reserve a dot column when at least one option is actually colored.
  // A select with no colors shows no dots at all (no "no color" placeholder).
  $: anyColored = options.some((o) => !!o.color);

  function toggle() {
    if (readOnly) return;
    open = !open;
    if (open && anchor) {
      const r = anchor.getBoundingClientRect();
      menuPos = { x: r.left, y: r.bottom + 4, width: r.width };
    }
  }
  function close() { open = false; }

  function select(opt: SelectOption) {
    value = opt.value;
    onChange?.(opt.value);
    close();
  }

  function clear() {
    value = "";
    onChange?.("");
    close();
  }

  function onKey(event: KeyboardEvent) {
    if (event.key === "Escape" && open) {
      event.stopPropagation();
      close();
    }
  }

  function onDocClick(event: MouseEvent) {
    if (!open) return;
    const target = event.target as Node | null;
    if (target && anchor && anchor.contains(target)) return;
    const pop = document.querySelector(".colored-select-popover");
    if (pop && target && pop.contains(target)) return;
    close();
  }

  function dotStyle(opt: SelectOption): string {
    const s = opt.color ? getSwatch(opt.color) : null;
    return s ? `background: ${s.hex};` : "";
  }

  function pillStyle(): string {
    if (!currentSwatch) return "";
    return `--chip-base: ${currentSwatch.hex};`;
  }
</script>

<svelte:window on:click={onDocClick} on:keydown={onKey} />

<span class="colored-select">
  <button
    type="button"
    class="colored-select-trigger"
    class:has-color={!!currentSwatch}
    class:read-only={readOnly}
    aria-label={ariaLabel || current?.label || current?.value || placeholder}
    aria-haspopup={readOnly ? undefined : "listbox"}
    aria-expanded={open}
    disabled={readOnly}
    bind:this={anchor}
    style={pillStyle()}
    on:click|stopPropagation={toggle}
  >
    {#if current}
      {#if currentSwatch}
        <span class="colored-select-dot" style={`background: ${currentSwatch.hex}`}></span>
      {/if}
      <span class="colored-select-label">{current.label ?? current.value}</span>
    {:else}
      <span class="colored-select-placeholder">{placeholder}</span>
    {/if}
    {#if !readOnly}
      <span class="colored-select-caret" aria-hidden="true">▾</span>
    {/if}
  </button>

  {#if open && menuPos}
    <div
      class="colored-select-popover"
      role="listbox"
      style={`left: ${menuPos.x}px; top: ${menuPos.y}px; min-width: ${menuPos.width}px;`}
    >
      {#if allowBlank}
        <button
          type="button"
          class="colored-select-row"
          class:selected={value === ""}
          role="option"
          aria-selected={value === ""}
          on:click|stopPropagation={clear}
        >
          {#if anyColored}
            <span class="colored-select-dot colored-select-dot-spacer"></span>
          {/if}
          <span class="colored-select-row-label muted">{placeholder}</span>
        </button>
      {/if}
      {#each options as opt}
        <button
          type="button"
          class="colored-select-row"
          class:selected={opt.value === value}
          role="option"
          aria-selected={opt.value === value}
          on:click|stopPropagation={() => select(opt)}
        >
          {#if opt.color}
            <span class="colored-select-dot" style={dotStyle(opt)}></span>
          {:else if anyColored}
            <span class="colored-select-dot colored-select-dot-spacer"></span>
          {/if}
          <span class="colored-select-row-label">{opt.label ?? opt.value}</span>
        </button>
      {/each}
    </div>
  {/if}
</span>

<style>
  .colored-select {
    position: relative;
    display: inline-block;
  }

  .colored-select-trigger {
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 8px;
    font: inherit;
    font-size: 13px;
    line-height: 1.2;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    cursor: pointer;
    transition: border-color 80ms linear, background-color 80ms linear;
    min-width: 96px;
  }
  .colored-select-trigger:hover {
    border-color: var(--accent);
  }
  .colored-select-trigger.read-only {
    cursor: default;
  }
  .colored-select-trigger.read-only:hover {
    border-color: var(--border);
  }
  .colored-select-trigger.read-only.has-color:hover {
    border-color: color-mix(in srgb, var(--chip-base) 40%, var(--border) 60%);
  }
  /* When the selected option has a color, render the whole trigger as a
     soft-tinted pill so the status is loud at a glance. */
  .colored-select-trigger.has-color {
    background: color-mix(in srgb, var(--chip-base) 12%, white 88%);
    border-color: color-mix(in srgb, var(--chip-base) 40%, var(--border) 60%);
  }
  :global([data-theme="dark"]) .colored-select-trigger.has-color {
    background: color-mix(in srgb, var(--chip-base) 22%, black 78%);
  }

  .colored-select-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    flex: none;
    border-radius: 50%;
    border: 1px solid rgba(0, 0, 0, 0.18);
  }
  /* Invisible same-size spacer: keeps labels aligned in a list that mixes
     colored and uncolored options, without presenting a "no color" swatch. */
  .colored-select-dot-spacer {
    background: none;
    border-color: transparent;
  }

  .colored-select-label,
  .colored-select-placeholder {
    line-height: 1.2;
  }
  .colored-select-placeholder {
    color: var(--text-3);
  }

  .colored-select-caret {
    margin-left: auto;
    font-size: 10px;
    color: var(--text-3);
    line-height: 1;
  }

  .colored-select-popover {
    position: fixed;
    z-index: var(--z-dropdown);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 4px;
    box-shadow: var(--elev-2);
    min-width: 140px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .colored-select-row {
    appearance: none;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 8px;
    background: transparent;
    border: none;
    border-radius: 5px;
    cursor: pointer;
    font: inherit;
    font-size: 13px;
    color: var(--text);
    text-align: left;
  }
  .colored-select-row:hover {
    background: var(--panel);
  }
  .colored-select-row.selected {
    background: var(--accent-soft);
  }
  .colored-select-row-label.muted {
    color: var(--text-3);
    font-style: italic;
  }
</style>
