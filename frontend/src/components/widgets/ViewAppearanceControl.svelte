<script lang="ts">
  // The per-view layout affordance (ADR-0069), rendered beside ViewSwitcher in
  // RegionActions. It sets the view's `ui.appearance` (mode + density) — the
  // ADR-0066 NodeList axes — through paneViews, orthogonal to the spec (ADR-0037
  // §3 keeps the spec presentation-free). A self-contained popover mirroring
  // ViewSwitcher's pattern; the pane reads the same `appearanceFor(kind)` and
  // re-renders at the chosen layout. Unset axes fall back to the pane default.
  import { paneViews } from "@/lib/stores/paneViews.svelte";

  let { kind }: { kind: string } = $props();

  let open = $state(false);
  const appearance = $derived(paneViews.appearanceFor(kind));
  const isSet = $derived(!!(appearance?.mode || appearance?.density));

  const MODES: { value: "card" | "tree"; label: string }[] = [
    { value: "card", label: "Cards" },
    { value: "tree", label: "Tree" },
  ];
  const DENSITIES: { value: "comfortable" | "compact" | "dense"; label: string }[] = [
    { value: "comfortable", label: "Comfortable" },
    { value: "compact", label: "Compact" },
    { value: "dense", label: "Dense" },
  ];

  function onWindowClick(event: MouseEvent): void {
    if (!(event.target as HTMLElement)?.closest?.(".view-appearance")) open = false;
  }
</script>

<svelte:window onclick={onWindowClick} />

<span class="view-appearance">
  <button
    class="pin-button view-appearance-trigger"
    class:active={open}
    class:has-appearance={isSet}
    type="button"
    title="Layout"
    aria-label="View layout"
    aria-haspopup="menu"
    aria-expanded={open}
    onmousedown={(event) => event.stopPropagation()}
    onclick={() => (open = !open)}
  >
    <span class="view-appearance-glyph" aria-hidden="true">▦</span>
  </button>
  {#if open}
    <div class="view-appearance-popover" role="menu">
      <div class="va-section">
        <span class="va-heading">Layout</span>
        <div class="va-options">
          {#each MODES as m (m.value)}
            <button
              class="va-option"
              class:selected={appearance?.mode === m.value}
              type="button"
              role="menuitemradio"
              aria-checked={appearance?.mode === m.value}
              onclick={() => void paneViews.setAppearance(kind, { mode: m.value })}
            >{m.label}</button>
          {/each}
        </div>
      </div>
      <div class="va-section">
        <span class="va-heading">Density</span>
        <div class="va-options">
          {#each DENSITIES as d (d.value)}
            <button
              class="va-option"
              class:selected={appearance?.density === d.value}
              type="button"
              role="menuitemradio"
              aria-checked={appearance?.density === d.value}
              onclick={() => void paneViews.setAppearance(kind, { density: d.value })}
            >{d.label}</button>
          {/each}
        </div>
      </div>
      {#if isSet}
        <button class="va-reset" type="button" onclick={() => void paneViews.clearAppearance(kind)}>
          Reset to default
        </button>
      {/if}
    </div>
  {/if}
</span>

<style>
  .view-appearance {
    position: relative;
    display: inline-flex;
  }

  .view-appearance-trigger {
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  /* A set layout tints the trigger like the switcher's has-view state, so it
     reads at a glance that this view carries a non-default look. */
  .view-appearance-trigger.has-appearance {
    color: var(--accent);
  }

  .view-appearance-glyph {
    font-size: var(--fs-md);
    line-height: 1;
  }

  .view-appearance-popover {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    z-index: 40;
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 180px;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--surface);
    box-shadow: 0 6px 18px var(--shadow2);
  }

  .va-section {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }

  .va-heading {
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--text-3);
  }

  .va-options {
    display: flex;
    gap: 4px;
  }

  .va-option {
    flex: 1 1 auto;
    padding: 4px 8px;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: transparent;
    color: var(--text-2);
    font-size: var(--fs-sm);
    cursor: pointer;
    transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
  }

  .va-option:hover {
    background: var(--inset);
    color: var(--text);
  }

  .va-option.selected {
    border-color: var(--accent);
    background: var(--accent-soft2);
    color: var(--accent);
    font-weight: 600;
  }

  .va-reset {
    padding: 3px 0;
    border: none;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-xs);
    text-align: left;
    cursor: pointer;
  }

  .va-reset:hover {
    color: var(--text);
  }
</style>
