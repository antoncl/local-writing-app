<script lang="ts">
  import { onDestroy } from "svelte";
  import type { ScopedTag } from "@/lib/types";
  import { pickerMembership } from "@/lib/utils/pickerSources";
  import { portalToBody } from "@/lib/actions/portal";
  import TagChip from "@/components/widgets/TagChip.svelte";

  export let value: string = "";
  export let knownTags: ScopedTag[] = [];
  // The current node's kind + sub-type — used to filter suggestions by tag
  // scope (a tag is suggested where its scope is empty or includes this).
  export let scopeKind: string = "";
  export let scopeEntryType: string = "";
  export let ariaLabel: string;
  export let placeholder: string = "Add tags…";
  // Emits the committed tags as a comma-joined string (the wire contract the
  // parent round-trips). A callback prop, not a `change` event, so it composes
  // with the runes-based FieldValueEditor and is directly testable.
  export let onChange: (value: string) => void = () => {};

  function parseTags(raw: string): string[] {
    return raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  // The committed tags come from `value` (the parent is the source of truth);
  // `entryText` is the in-progress, uncommitted input. Typing stays free-form and
  // only *crystallises* into chips on a comma, Enter, or when the field loses
  // focus (#247) — so the fast "just type them" habit keeps working, tidily.
  let entryText = "";
  let inputEl: HTMLInputElement | null = null;

  $: chips = parseTags(value);
  // "Known" means present in the vocabulary at all — a known-but-out-of-scope tag
  // is still known (not pending). Scope only governs what the + *suggests*.
  $: knownKeys = new Set(knownTags.map((t) => t.name.toLowerCase()));
  function isKnown(tag: string): boolean {
    return knownKeys.has(tag.toLowerCase());
  }

  function commit(next: string[]) {
    onChange(next.join(", "));
  }

  function addTag(tag: string) {
    const clean = tag.trim();
    if (!clean) return;
    const key = clean.toLowerCase();
    if (chips.some((t) => t.toLowerCase() === key)) return;
    commit([...chips, clean]);
  }

  function removeTag(tag: string) {
    const key = tag.toLowerCase();
    commit(chips.filter((t) => t.toLowerCase() !== key));
  }

  function crystallize() {
    const tokens = parseTags(entryText);
    if (tokens.length === 0) {
      entryText = "";
      return;
    }
    const next = [...chips];
    const seen = new Set(next.map((t) => t.toLowerCase()));
    for (const token of tokens) {
      const key = token.toLowerCase();
      if (!seen.has(key)) {
        next.push(token);
        seen.add(key);
      }
    }
    entryText = "";
    commit(next);
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      crystallize();
    } else if (event.key === "Backspace" && entryText === "" && chips.length > 0) {
      // Empty-input backspace removes the last chip — the token-field convention.
      event.preventDefault();
      removeTag(chips[chips.length - 1]);
    }
  }

  function focusField(event: MouseEvent) {
    // Clicking bare field space focuses the input; clicks on a chip's × or the +
    // button handle themselves.
    if ((event.target as HTMLElement).closest("button")) return;
    inputEl?.focus();
  }

  // ---- the + suggestion popover (pick from the scoped roster) ----------------
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
  $: selectedKeys = new Set(chips.map((t) => t.toLowerCase()));

  let open = false;
  let position: { x: number; y: number; width: number } | null = null;
  let anchorEl: HTMLDivElement | null = null;
  let rafId = 0;

  // Position the (body-portaled) popover from the anchor's viewport rect. Only
  // reassign when the on-screen anchor actually moved, so the per-frame tracking
  // loop doesn't churn reactivity while the canvas sits idle.
  function measure(el: HTMLElement) {
    const b = el.getBoundingClientRect();
    const next = { x: b.left, y: b.bottom + 4, width: Math.min(320, Math.max(220, b.width)) };
    if (!position || position.x !== next.x || position.y !== next.y || position.width !== next.width) {
      position = next;
    }
  }

  // #245: the popover portals to <body> and positions off the anchor's viewport
  // rect. Inside a zoomed/panned SvelteFlow canvas the anchor moves on screen
  // WITHOUT firing scroll/resize, so re-measure every frame while open — the menu
  // stays glued to the node at native (1×) size (anchor-track, not scale-with-zoom).
  function track() {
    if (!open || !anchorEl) return;
    measure(anchorEl);
    rafId = requestAnimationFrame(track);
  }

  function close() {
    open = false;
    position = null;
    if (rafId) {
      cancelAnimationFrame(rafId);
      rafId = 0;
    }
  }

  function toggle(event: MouseEvent) {
    if (open) {
      close();
      return;
    }
    measure(anchorEl ?? (event.currentTarget as HTMLElement));
    open = true;
    rafId = requestAnimationFrame(track);
  }

  onDestroy(close);

  function handleOutsidePointerdown(event: PointerEvent) {
    if (!open || !anchorEl) return;
    const target = event.target;
    if (target instanceof Node && anchorEl.contains(target)) return;
    // The menu portals to <body> (outside anchorEl), so a pointerdown inside it
    // must not count as "outside" — otherwise it closes before the suggestion's
    // click lands. Query the portaled node the same way its sibling pickers do.
    const menu = document.querySelector(".tag-picker");
    if (menu && target instanceof Node && menu.contains(target)) return;
    close();
  }
</script>

<svelte:window on:pointerdown={handleOutsidePointerdown} />

<div class="tag-picker-anchor" bind:this={anchorEl}>
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <!-- Clicking bare field space just focuses the input, which is already in the
       tab order; the real controls are the input, chips, and + button. -->
  <div class="tag-field" on:click={focusField}>
    <input
      class="tag-entry"
      bind:this={inputEl}
      bind:value={entryText}
      placeholder={chips.length ? "" : placeholder}
      aria-label={ariaLabel}
      on:keydown={onKeydown}
      on:blur={crystallize}
    />
    {#each chips as tag (tag)}
      <TagChip name={tag} pending={!isKnown(tag)} removable ariaContext={ariaLabel} onRemove={() => removeTag(tag)} />
    {/each}
    <button class="tag-picker-toggle" type="button" title="Add known tags" on:click|stopPropagation={toggle}>+</button>
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
            on:click={() => addTag(tag.name)}
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

  .tag-field {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
    align-items: center;
    min-height: 34px;
    padding: 6px 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    cursor: text;
  }
  .tag-field:focus-within {
    border-color: var(--accent);
  }

  .tag-entry {
    flex: 0 1 150px;
    min-width: 90px;
    height: 24px;
    padding: 0;
    border: none;
    outline: none;
    background: transparent;
    font-size: var(--fs-md);
    color: var(--text);
  }

  .tag-picker-toggle {
    margin-left: auto;
    width: 26px;
    height: 26px;
    padding: 0;
    border: 1px dashed var(--border-strong);
    border-radius: 8px;
    background: var(--inset);
    color: var(--text-2);
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
