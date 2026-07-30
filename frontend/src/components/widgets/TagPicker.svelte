<script lang="ts">
  import { onDestroy } from "svelte";
  import type { ScopedTag } from "@/lib/types";
  import { pickerMembership } from "@/lib/utils/pickerSources";
  import { portalToBody } from "@/lib/actions/portal";
  import TagChip from "@/components/widgets/TagChip.svelte";
  import TagRosterPopover from "@/components/widgets/TagRosterPopover.svelte";
  import { parseTagList, tagColorMap } from "@/lib/utils/tags";
  import { assistantTagGovernance, projectTagGovernance } from "@/lib/utils/tagGovernance";

  export let value: string = "";
  export let knownTags: ScopedTag[] = [];
  // The current node's kind + sub-type — used to filter suggestions by tag
  // scope (a tag is suggested where its scope is empty or includes this).
  export let scopeKind: string = "";
  export let scopeEntryType: string = "";
  export let ariaLabel: string;
  export let placeholder: string = "Add tags…";
  // Which vocabulary this field's roster comes from. Both govern from the + now
  // (scope / rename / merge for project tags; rename / merge / colour for the
  // flat, scope-less assistant tags) — the difference is the injected governance
  // adapter, chosen here by origin. Decided once, at the pane that picks the
  // roster (App feeds the assistant/prompt pane a mixed roster), and threaded
  // down — never re-derived from the document kind here (#247).
  export let origin: "project" | "assistant" = "project";
  // Emits the committed tags as a comma-joined string (the wire contract the
  // parent round-trips). A callback prop, not a `change` event, so it composes
  // with the runes-based FieldValueEditor and is directly testable.
  export let onChange: (value: string) => void = () => {};

  // The committed tags come from `value` (the parent is the source of truth);
  // `entryText` is the in-progress, uncommitted input. Typing stays free-form and
  // only *crystallises* into chips on a comma, Enter, or when the field loses
  // focus (#247) — so the fast "just type them" habit keeps working, tidily.
  let entryText = "";
  let inputEl: HTMLInputElement | null = null;

  $: chips = parseTagList(value);
  // "Known" means present in the vocabulary at all — a known-but-out-of-scope tag
  // is still known (not pending). Scope only governs what the + *suggests*.
  $: knownKeys = new Set(knownTags.map((t) => t.name.toLowerCase()));
  // Lowercased-name → swatch id, so a committed chip renders its tag's colour.
  $: colorMap = tagColorMap(knownTags);
  // Per-chip pending state, computed in ONE reactive statement that reads both
  // `chips` and `knownKeys` — so "will be created" re-evaluates when the roster
  // loads or a just-created tag is registered. A template `pending={!isKnown(tag)}`
  // would NOT: Svelte can't see `knownKeys` through the `isKnown()` call, so a
  // chip would stay outlined after the roster arrives (feedback_svelte5_reactivity_traps).
  $: chipStates = chips.map((tag) => ({ tag, pending: !knownKeys.has(tag.toLowerCase()) }));

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
    const tokens = parseTagList(entryText);
    entryText = "";
    if (tokens.length === 0) return;
    const next = [...chips];
    const seen = new Set(next.map((t) => t.toLowerCase()));
    let changed = false;
    for (const token of tokens) {
      const key = token.toLowerCase();
      if (!seen.has(key)) {
        next.push(token);
        seen.add(key);
        changed = true;
      }
    }
    // Don't fire onChange (and a redundant autosave) when every token was already
    // present — e.g. typing an existing tag's name and pressing Enter.
    if (changed) commit(next);
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
  function inScope(tag: ScopedTag, kind: string, entryType: string): boolean {
    // Tag scopes stay the degenerate type-leaf subset (ADR-0023) — read the
    // legacy {kinds, entryTypes} view of the scope's `sources`.
    const { kinds, entryTypes } = pickerMembership(tag.scope);
    if (kinds.length === 0 && Object.keys(entryTypes).length === 0) return true;
    if (kinds.length && !kinds.includes(kind)) return false;
    const subs = entryTypes[kind];
    if (subs && subs.length && !subs.includes(entryType)) return false;
    return true;
  }
  // scopeKind/scopeEntryType are referenced IN the reactive statement so `$:`
  // tracks them — filtering through a closure that merely reads them would not
  // re-run when the node's type changes (feedback_svelte5_reactivity_traps).
  $: suggestions = knownTags.filter((tag) => inScope(tag, scopeKind, scopeEntryType));
  $: selectedKeys = new Set(chips.map((t) => t.toLowerCase()));
  // The governance operations for this roster's vocabulary — the only thing that
  // differs between the two origins; the surface is one component (#247 PR-3).
  $: governanceAdapter = origin === "assistant" ? assistantTagGovernance : projectTagGovernance;

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
    // The governance rows' SwatchPicker portals its palette to <body> too, so a
    // click on a swatch cell must not read as "outside" and close us before the
    // colour is picked (#247).
    const swatch = document.querySelector(".swatch-picker-popover");
    if (swatch && target instanceof Node && swatch.contains(target)) return;
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
    {#each chipStates as chip (chip.tag)}
      <TagChip name={chip.tag} pending={chip.pending} color={colorMap.get(chip.tag.toLowerCase()) ?? null} removable ariaContext={ariaLabel} onRemove={() => removeTag(chip.tag)} />
    {/each}
    <!-- mousedown|preventDefault keeps the input focused, so clicking + to open the
         roster doesn't blur→crystallise the half-typed text into a stray chip. -->
    <button
      class="tag-picker-toggle"
      type="button"
      title="Add known tags"
      on:mousedown|preventDefault
      on:click|stopPropagation={toggle}
    >+</button>
  </div>
  {#if open && position}
    <div
      class="tag-picker governing"
      style={`left: ${position.x}px; top: ${position.y}px; width: ${position.width}px;`}
      aria-label={`${ariaLabel} known tags`}
      use:portalToBody
    >
      <!-- The + is the lightweight governance surface for both vocabularies; the
           adapter decides which ops (assistant tags hide scope). -->
      <TagRosterPopover
        tags={suggestions}
        selectedKeys={selectedKeys}
        adapter={governanceAdapter}
        ariaLabel={ariaLabel}
        onAdd={(name) => addTag(name)}
      />
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

  /* The popover is a body-portaled frame around the governance roster, which
     owns its own column layout + internal padding. */
  .tag-picker {
    position: fixed;
    z-index: 10000;
    display: flex;
    flex-direction: column;
    max-width: min(360px, calc(100vw - 24px));
    max-height: min(260px, calc(100vh - 24px));
    overflow: visible;
    border: 1px solid var(--divider);
    border-radius: 6px;
    background: var(--surface);
    box-shadow: var(--elev-2);
  }
</style>
