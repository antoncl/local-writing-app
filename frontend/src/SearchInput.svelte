<script lang="ts">
  // SearchInput — find-style input used by NodeList and (later) by any
  // NodeRow children that contain large enough sub-lists to want their
  // own search. See [[decisions-ui-widget-taxonomy]] / NodeList design
  // session (2026-06-22).
  //
  // Holds value only — no filtering. Caller computes filtered output
  // because the matcher (title vs title+tags+aliases vs free text) is
  // domain-specific.
  //
  // Keyboard:
  //   - Esc: clear the value if non-empty, otherwise blur.
  //   - Cmd/Ctrl+F (handled by focusTargetStore): focuses the
  //     nearest-in-scope SearchInput. The persistent badge shows which
  //     one is the current target.

  import { onMount, onDestroy } from "svelte";
  import { registerFindTarget, isCurrentTarget } from "./focusTargetStore";
  import type { Readable } from "svelte/store";

  export let value: string = "";
  export let placeholder: string = "";
  export let onChange: ((value: string) => void) | undefined = undefined;
  export let clearable: boolean = true;
  // 0 by default: sync. Consumers opt in to debounce by passing a ms
  // value; useful if the matcher is expensive to recompute per keystroke.
  export let debounceMs: number = 0;
  // Mac platforms show ⌘F; everything else shows Ctrl+F. Cheap detect.
  // Falls back to Ctrl+F server-side / before mount.
  let shortcutLabel = "Ctrl+F";

  let input: HTMLInputElement | undefined;
  let registrationId: number | null = null;
  let isActiveTarget: Readable<boolean> | null = null;
  let badgeActive = false;
  let badgeUnsub: (() => void) | undefined;
  let debounceTimer: ReturnType<typeof setTimeout> | undefined;

  onMount(() => {
    if (typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform)) {
      shortcutLabel = "⌘F";
    }
    if (input) {
      const reg = registerFindTarget(input, "search");
      registrationId = reg.id;
      isActiveTarget = isCurrentTarget(reg.id);
      badgeUnsub = isActiveTarget.subscribe((v) => (badgeActive = v));
    }
  });

  onDestroy(() => {
    badgeUnsub?.();
    if (debounceTimer) clearTimeout(debounceTimer);
  });

  function handleInput(event: Event) {
    const next = (event.currentTarget as HTMLInputElement).value;
    value = next;
    if (!onChange) return;
    if (debounceMs > 0) {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => onChange?.(next), debounceMs);
    } else {
      onChange(next);
    }
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      if (value) {
        // Clear without losing focus — user is likely about to search again.
        event.preventDefault();
        value = "";
        onChange?.("");
      } else {
        // Empty input + Esc = blur and step back. Useful for the "I'm done
        // searching, hand keyboard nav back to the row list" case.
        event.preventDefault();
        input?.blur();
      }
    }
  }

  function clearValue() {
    value = "";
    onChange?.("");
    input?.focus();
  }
</script>

<span class="search-input" class:has-value={!!value} class:focused-active={badgeActive}>
  <svg class="search-input-glyph" aria-hidden="true" viewBox="0 0 16 16" width="14" height="14">
    <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.5" />
    <line x1="10.3" y1="10.3" x2="13" y2="13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
  </svg>
  <input
    bind:this={input}
    class="search-input-field"
    type="search"
    {placeholder}
    {value}
    on:input={handleInput}
    on:keydown={handleKeydown}
  />
  {#if clearable && value}
    <button
      type="button"
      class="search-input-clear"
      title="Clear search (Esc)"
      tabindex="-1"
      on:click={clearValue}
    >×</button>
  {/if}
  <span
    class="search-input-shortcut"
    class:active={badgeActive}
    aria-hidden="true"
    title={badgeActive ? `Press ${shortcutLabel} to focus this search` : `${shortcutLabel} targets a different search`}
  >{shortcutLabel}</span>
</span>

<style>
  /* Editorial Card direction (Node widget design pass, 2026-06-22):
     framed input with a leading magnifier glyph and a keycap-style
     shortcut badge that "presses in" when this input is the resolved
     Ctrl/Cmd+F target. Color tokens come from styles.css :root. */
  .search-input {
    position: relative;
    display: inline-flex;
    align-items: center;
    width: 100%;
    border: 1px solid var(--border);
    border-radius: 9px;
    background: var(--surface);
    transition: border-color 120ms ease, box-shadow 120ms ease;
    box-shadow: 0 1px 2px var(--shadow);
  }

  .search-input:focus-within {
    border-color: var(--accent);
    box-shadow: 0 0 0 1.5px var(--accent-soft2), 0 1px 2px var(--shadow);
  }

  .search-input-glyph {
    flex: none;
    margin-left: 10px;
    color: var(--text-3);
  }

  .search-input:focus-within .search-input-glyph {
    color: var(--accent);
  }

  .search-input-field {
    flex: 1 1 auto;
    width: 100%;
    padding: 7px 8px 7px 8px;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    outline: none;
  }

  /* Hide the native search clear (we have our own × button). */
  .search-input-field::-webkit-search-cancel-button {
    -webkit-appearance: none;
    appearance: none;
  }

  .search-input-field::placeholder {
    color: var(--text-3);
  }

  .search-input-clear {
    flex: none;
    width: 20px;
    height: 20px;
    padding: 0;
    margin-right: 4px;
    border: 0;
    border-radius: 999px;
    background: var(--inset);
    color: var(--text-2);
    font-size: 14px;
    line-height: 1;
    cursor: pointer;
    transition: background 120ms ease, color 120ms ease;
  }

  .search-input-clear:hover {
    background: var(--accent-soft);
    color: var(--accent-strong);
  }

  /* Keycap badge. Dim "available" state shows a raised key (1px bottom
     border = the keycap edge). Active state presses in — flat against
     the accent and shadow reverses to an inset. */
  .search-input-shortcut {
    flex: none;
    margin-right: 7px;
    padding: 2px 8px 3px;
    border: 1px solid var(--border);
    border-bottom-width: 2px;
    border-radius: 5px;
    background: var(--surface);
    color: var(--text-3);
    font-size: 10.5px;
    font-weight: 700;
    letter-spacing: 0.35px;
    line-height: 1;
    pointer-events: none;
    user-select: none;
    transition: background 120ms ease, color 120ms ease, border-color 120ms ease,
      box-shadow 120ms ease, transform 120ms ease;
  }

  .search-input-shortcut.active {
    background: var(--accent);
    color: #ffffff;
    border-color: var(--accent-deep);
    border-bottom-width: 1px;
    box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.18);
    transform: translateY(1px);
  }
</style>
