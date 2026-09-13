<script lang="ts">
  // Custom dropdown that mirrors `<select>` but renders each option with
  // its swatch color (when set). Selected value displays as a tinted pill.
  // Used for fields like `status` so completeness is visible at a glance
  // in the metadata pane and (later) the scene tree row.
  //
  // Falls back to the neutral chip when an option has no color, so this
  // widget is safe to use even when only SOME options are colored.
  //
  // Three optional, additive abilities (#1904) for a head-of-panel use like
  // the Details rail's type control: `icon` renders a leading glyph on the
  // trigger, `quiet` makes the trigger read as rest text (no border/surface
  // until hover), and `footer` renders a trailing action row under a divider
  // inside the popover.

  import { getSwatch } from "@/lib/utils/colors";
  import { anchoredPopover } from "@/lib/actions/anchoredPopover";
  import type { SelectOption } from "@/lib/types";
  import type { Snippet } from "svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";

  let {
    value = "",
    options = [],
    // When true, the trigger renders a small placeholder when value is "".
    allowBlank = true,
    placeholder = "(none)",
    ariaLabel = "",
    onChange = undefined,
    // Read-only display (#64): the trigger pill renders identically (dot +
    // label + tint) but is inert — no popover, no hover affordance, no caret.
    // Exception: when a `footer` is also provided, the trigger still opens —
    // readOnly locks the VALUE, but a footer action is independent of the
    // value, so there is still something to open the list for (#1904). The
    // option rows render disabled/inert in that case; the footer works.
    readOnly = false,
    // Option values shown at rest but never offered — the trigger still names
    // one that is held. An authoring host lists the field's derived state here
    // (#1911); a host that references a value (a view filter) keeps every
    // option pickable.
    omitFromPick = [],
    // Leading glyph on the trigger (Tabler class list), e.g. "ti ti-user".
    icon = null,
    // Trigger reads as rest text: no border/surface until hover (#1904).
    quiet = false,
    footer = undefined,
  }: {
    value?: string;
    options?: SelectOption[];
    allowBlank?: boolean;
    placeholder?: string;
    ariaLabel?: string;
    onChange?: (value: string) => void;
    readOnly?: boolean;
    omitFromPick?: string[];
    icon?: string | null;
    quiet?: boolean;
    footer?: Snippet<[{ close: () => void }]>;
  } = $props();

  let open = $state(false);
  // Reactive (not a plain `let`): the action reads it via the `use:` param,
  // and a plain `let` bound with `bind:this` isn't tracked under Svelte 5
  // runes, so the param would still be stale/undefined at first open.
  let anchor: HTMLButtonElement | undefined = $state();

  const current = $derived(options.find((o) => o.value === value) ?? null);
  // Resolve the swatch hex when the selected option carries a color id.
  const currentSwatch = $derived(current?.color ? getSwatch(current.color) : null);
  // Only reserve a dot column when at least one option is actually colored.
  // A select with no colors shows no dots at all (no "no color" placeholder).
  const anyColored = $derived(options.some((o) => !!o.color));

  // The open popover, for focus management (#1904 review). The popover is
  // body-portaled, so without this a keyboard user who opens the list finds
  // focus still on the trigger and Tab walking away from the rows: focus
  // moves INTO the list on open (the selected row; the footer action when the
  // rows are inert), Arrow keys walk rows + footer, and closing hands focus
  // back to the trigger when it was inside the list.
  let popEl: HTMLDivElement | undefined = $state();

  function toggle() {
    if (readOnly && !footer) return;
    open = !open;
  }
  function close() {
    const active = document.activeElement;
    const inside = !!popEl && (popEl.contains(active) || active === document.body);
    open = false;
    if (inside) anchor?.focus();
  }

  $effect(() => {
    if (!open || !popEl) return;
    const target = readOnly
      ? popEl.querySelector<HTMLElement>(".colored-select-footer button")
      : (popEl.querySelector<HTMLElement>(".colored-select-row.selected") ?? popEl.querySelector<HTMLElement>("button"));
    target?.focus();
  });

  function select(opt: SelectOption) {
    if (readOnly) return;
    value = opt.value;
    onChange?.(opt.value);
    close();
  }

  function clear() {
    if (readOnly) return;
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

  // Arrow keys walk every button in the popover — rows and footer actions —
  // wrapping at both ends, like a native <select>'s list.
  function onPopKey(event: KeyboardEvent) {
    if (!popEl || (event.key !== "ArrowDown" && event.key !== "ArrowUp")) return;
    const items = Array.from(popEl.querySelectorAll<HTMLElement>("button"));
    if (items.length === 0) return;
    const idx = items.indexOf(document.activeElement as HTMLElement);
    const step = event.key === "ArrowDown" ? 1 : -1;
    const next = idx < 0 ? (step > 0 ? 0 : items.length - 1) : (idx + step + items.length) % items.length;
    event.preventDefault();
    items[next].focus();
  }

  // Tab out of the popover (or focus otherwise leaving it and the trigger)
  // closes it — the body-portaled list must not stay open behind the page.
  function onPopFocusOut(event: FocusEvent) {
    if (!open) return;
    const to = event.relatedTarget as Node | null;
    if (to && ((popEl && popEl.contains(to)) || (anchor && anchor.contains(to)))) return;
    open = false;
  }

  function onDocClick(event: MouseEvent) {
    if (!open) return;
    const target = event.target as Node | null;
    if (target && anchor && anchor.contains(target)) return;
    if (popEl && target && popEl.contains(target)) return;
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

<svelte:window onclick={onDocClick} onkeydown={onKey} />

<span class="colored-select">
  <button
    type="button"
    class="colored-select-trigger"
    class:has-color={!!currentSwatch}
    class:read-only={readOnly && !footer}
    class:quiet
    aria-label={ariaLabel || current?.label || current?.value || placeholder}
    title={current ? (current.label ?? current.value) : undefined}
    aria-haspopup={readOnly && !footer ? undefined : "listbox"}
    aria-expanded={open}
    disabled={readOnly && !footer}
    bind:this={anchor}
    style={pillStyle()}
    onclick={(e) => {
      e.stopPropagation();
      toggle();
    }}
  >
    {#if icon}
      <i class={`colored-select-icon ${icon}`} aria-hidden="true"></i>
    {/if}
    {#if current}
      {#if currentSwatch}
        <span class="colored-select-dot" style={`background: ${currentSwatch.hex}`}></span>
      {/if}
      <span class="colored-select-label">{current.label ?? current.value}</span>
    {:else}
      <span class="colored-select-placeholder">{placeholder}</span>
    {/if}
    {#if !readOnly || footer}
      <span class="colored-select-caret" aria-hidden="true"><GroupCaret size="xs" /></span>
    {/if}
  </button>

  {#if open}
    <!-- The listbox holds only options; a footer action is its SIBLING, not a
         child — a non-option inside role="listbox" is an ARIA authoring error.
         Keyboard handling lives on the shared wrapper so it spans both. -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="colored-select-popover"
      bind:this={popEl}
      use:anchoredPopover={{ anchor, gap: 4, matchWidth: true }}
      onkeydown={onPopKey}
      onfocusout={onPopFocusOut}
    >
    <div class="colored-select-list" role="listbox">
      {#if allowBlank}
        <button
          type="button"
          class="colored-select-row"
          class:selected={value === ""}
          class:disabled={readOnly}
          role="option"
          aria-selected={value === ""}
          aria-disabled={readOnly ? "true" : undefined}
          onclick={(e) => {
            e.stopPropagation();
            clear();
          }}
        >
          {#if anyColored}
            <span class="colored-select-dot colored-select-dot-spacer"></span>
          {/if}
          <span class="colored-select-row-label muted">{placeholder}</span>
        </button>
      {/if}
      {#each options.filter((o) => !omitFromPick.includes(o.value)) as opt}
        <button
          type="button"
          class="colored-select-row"
          class:selected={opt.value === value}
          class:disabled={readOnly}
          role="option"
          aria-selected={opt.value === value}
          aria-disabled={readOnly ? "true" : undefined}
          onclick={(e) => {
            e.stopPropagation();
            select(opt);
          }}
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
      {#if footer}
        <div class="colored-select-footer">{@render footer({ close })}</div>
      {/if}
    </div>
  {/if}
</span>

<style>
  .colored-select {
    position: relative;
    display: inline-block;
    min-width: 0;
    max-width: 100%;
  }

  .colored-select-trigger {
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 8px;
    font: inherit;
    font-size: var(--fs-md);
    line-height: 1.2;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    cursor: pointer;
    transition: border-color 80ms linear, background-color 80ms linear;
    /* Shrink to the value column instead of wrapping the label to a second line:
       a long option like "Automatic (alias match)" truncates with an ellipsis and
       the full text lives in the trigger's title tooltip (#1438). min-width:0 lets
       the label's ellipsis engage inside the flex row. */
    min-width: 0;
    max-width: 100%;
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
  /* Quiet face (#1904): the trigger reads as rest text — no border/surface —
     until hover shows the rail's inset (RailScalarCell's `.fr-rest-hit:hover`
     recipe). Declared BEFORE `.has-color` so a coloured option's tint still
     wins the cascade (not the case for types today, but keeps it sane). */
  .colored-select-trigger.quiet {
    background: transparent;
    border-color: transparent;
  }
  .colored-select-trigger.quiet:hover {
    background: color-mix(in srgb, var(--inset) 70%, transparent);
    border-color: transparent;
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

  /* Leading glyph (#1904) — same recipe as the old `.rail-type-icon`. */
  .colored-select-icon {
    flex: none;
    color: var(--text-3);
    font-size: var(--fs-lg);
    line-height: 1;
  }

  .colored-select-label,
  .colored-select-placeholder {
    line-height: 1.2;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .colored-select-placeholder {
    color: var(--text-3);
  }

  .colored-select-caret {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
  }

  .colored-select-popover {
    /* `anchoredPopover` owns position/left/top (body-portaled + viewport-
       anchored, #1587); this carries only the chrome + the portaled elevation
       tier, which must clear the modal layer itself (Modal 2000, DirectoryPicker
       2200) or the menu opens BEHIND a dialog that embeds this select — e.g.
       the create-project wizard's review step (#556). Matches every other
       portaled popover's z-index. Deliberately NOT `--z-dropdown`: that token
       (100) also drives non-portaled nodes (WorkspaceNode), which must stay in
       the normal stack. */
    z-index: 10000;
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

  /* The option rows' listbox; the footer stacks under it inside the popover. */
  .colored-select-list {
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
    font-size: var(--fs-md);
    color: var(--text);
    text-align: left;
  }
  .colored-select-row:hover {
    background: var(--panel);
  }
  .colored-select-row.selected {
    background: var(--accent-soft);
  }
  /* readOnly + footer (#1904): rows stay visible but inert — readOnly locks
     the value, the footer action below them is what the popover is for. */
  .colored-select-row.disabled {
    color: var(--text-3);
    cursor: default;
  }
  .colored-select-row.disabled:hover {
    background: transparent;
  }
  .colored-select-row-label.muted {
    color: var(--text-3);
    font-style: italic;
  }

  /* Trailing footer action (#1904), e.g. "Edit type…" under the option rows. */
  .colored-select-footer {
    margin-top: 2px;
    padding-top: 4px;
    border-top: 1px solid var(--divider);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .colored-select-footer :global(button) {
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
    font-size: var(--fs-md);
    color: var(--text-2);
    text-align: left;
    width: 100%;
  }
  .colored-select-footer :global(button):hover {
    background: var(--panel);
    color: var(--text);
  }
</style>
