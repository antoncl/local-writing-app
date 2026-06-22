<script lang="ts">
  // Custom dropdown that mirrors `<select>` but renders each option with
  // its swatch color (when set). Selected value displays as a tinted pill.
  // Used for fields like `status` so completeness is visible at a glance
  // in the metadata pane and (later) the scene tree row.
  //
  // Falls back to the neutral chip when an option has no color, so this
  // widget is safe to use even when only SOME options are colored.

  import { getSwatch } from "./colors";
  import type { SelectOption } from "./types";

  export let value: string = "";
  export let options: SelectOption[] = [];
  // When true, the trigger renders a small placeholder when value is "".
  export let allowBlank: boolean = true;
  export let placeholder: string = "(none)";
  export let ariaLabel: string = "";
  export let onChange: ((value: string) => void) | undefined = undefined;

  let open = false;
  let anchor: HTMLButtonElement | undefined;

  $: current = options.find((o) => o.value === value) ?? null;
  // Resolve the swatch hex when the selected option carries a color id.
  $: currentSwatch = current?.color ? getSwatch(current.color) : null;

  function toggle() { open = !open; }
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
    aria-label={ariaLabel || current?.label || current?.value || placeholder}
    aria-haspopup="listbox"
    aria-expanded={open}
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
    <span class="colored-select-caret" aria-hidden="true">▾</span>
  </button>

  {#if open}
    <div class="colored-select-popover" role="listbox">
      {#if allowBlank}
        <button
          type="button"
          class="colored-select-row"
          class:selected={value === ""}
          role="option"
          aria-selected={value === ""}
          on:click|stopPropagation={clear}
        >
          <span class="colored-select-dot colored-select-dot-empty"></span>
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
          {:else}
            <span class="colored-select-dot colored-select-dot-empty"></span>
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
    background: var(--ctx-surface, #fff);
    border: 1px solid var(--ctx-border, #cdd8d3);
    border-radius: 6px;
    color: var(--ctx-text, #28332f);
    cursor: pointer;
    transition: border-color 80ms linear, background-color 80ms linear;
    min-width: 96px;
  }
  .colored-select-trigger:hover {
    border-color: var(--ctx-accent, #3f7d68);
  }
  /* When the selected option has a color, render the whole trigger as a
     soft-tinted pill so the status is loud at a glance. */
  .colored-select-trigger.has-color {
    background: color-mix(in srgb, var(--chip-base) 12%, white 88%);
    border-color: color-mix(in srgb, var(--chip-base) 40%, var(--ctx-border, #cdd8d3) 60%);
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
  .colored-select-dot-empty {
    background: repeating-linear-gradient(
      45deg,
      transparent 0 2px,
      rgba(0, 0, 0, 0.18) 2px 3px
    );
  }

  .colored-select-label,
  .colored-select-placeholder {
    line-height: 1.2;
  }
  .colored-select-placeholder {
    color: var(--ctx-text-3, #6c7872);
  }

  .colored-select-caret {
    margin-left: auto;
    font-size: 10px;
    color: var(--ctx-text-3, #6c7872);
    line-height: 1;
  }

  .colored-select-popover {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    z-index: 100;
    background: var(--ctx-surface, #fff);
    border: 1px solid var(--ctx-border, #cdd8d3);
    border-radius: 8px;
    padding: 4px;
    box-shadow: 0 6px 16px rgba(40, 60, 52, 0.18);
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
    color: var(--ctx-text, #28332f);
    text-align: left;
  }
  .colored-select-row:hover {
    background: var(--ctx-panel-2, #eef3f0);
  }
  .colored-select-row.selected {
    background: var(--ctx-accent-soft, #e2efe9);
  }
  .colored-select-row-label.muted {
    color: var(--ctx-text-3, #6c7872);
    font-style: italic;
  }
</style>
