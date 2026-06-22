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

<span class="search-input" class:has-value={!!value}>
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
  /* Visual chrome is provisional — see [[decisions-ui-widget-taxonomy]]
     "Claude Design pass" task. The intent is to give the badge enough
     contrast in the active state that users can read which input
     Ctrl/Cmd+F will fire. */
  .search-input {
    position: relative;
    display: inline-flex;
    align-items: center;
    width: 100%;
  }

  .search-input-field {
    flex: 1 1 auto;
    width: 100%;
    padding: 6px 60px 6px 8px;
    border: 1px solid #cbd6d2;
    border-radius: 4px;
    background: #ffffff;
    color: inherit;
    font: inherit;
  }

  /* Hide the native search clear (we have our own × button). */
  .search-input-field::-webkit-search-cancel-button {
    -webkit-appearance: none;
    appearance: none;
  }

  .search-input-field:focus {
    outline: 2px solid #2f6f5e;
    outline-offset: -1px;
  }

  .search-input-clear {
    position: absolute;
    right: 44px;
    top: 50%;
    transform: translateY(-50%);
    width: 18px;
    height: 18px;
    padding: 0;
    border: 0;
    border-radius: 999px;
    background: #dfe6e3;
    color: #4d5753;
    font-size: 14px;
    line-height: 1;
    cursor: pointer;
  }

  .search-input-clear:hover {
    background: #c8d2cd;
  }

  .search-input-shortcut {
    position: absolute;
    right: 6px;
    top: 50%;
    transform: translateY(-50%);
    padding: 1px 6px;
    border-radius: 3px;
    background: #eef2f0;
    color: #94a09a;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.4px;
    pointer-events: none;
    user-select: none;
    transition: background 120ms ease, color 120ms ease;
  }

  .search-input-shortcut.active {
    background: #2f6f5e;
    color: #ffffff;
  }
</style>
