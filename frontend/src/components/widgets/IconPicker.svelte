<script lang="ts">
  import { CURATED_ICON_CATEGORIES, CURATED_ICONS } from "@/lib/utils/fieldIcons";

  interface Props {
    // The current icon override (null/"" = inheriting the field-type default).
    value?: string | null;
    // The type's default glyph (shown as the reset target).
    defaultGlyph: string;
    // Field display name, for the header.
    fieldLabel?: string;
    onSelect?: (icon: string | null) => void;
    onClose?: () => void;
  }

  let { value = null, defaultGlyph, fieldLabel = "field", onSelect, onClose }: Props = $props();

  let query = $state("");
  const trimmed = $derived(query.trim().toLowerCase());
  // When searching, show a single flat filtered list; otherwise the themed
  // category grid.
  const filtered = $derived(
    trimmed ? CURATED_ICONS.filter((name) => name.includes(trimmed)) : [],
  );

  function choose(icon: string) {
    onSelect?.(icon);
  }
  function reset() {
    onSelect?.(null);
  }
</script>

<div class="icon-picker" role="dialog" aria-label={`Icon for ${fieldLabel}`}>
  <div class="ip-head">
    <span class="ip-title">Icon for <span class="ip-field">{fieldLabel}</span></span>
    <button type="button" class="ip-reset" onclick={reset}>reset to default</button>
  </div>
  <div class="ip-body">
    <input
      class="ip-search"
      placeholder="Search icons…"
      aria-label="Search icons"
      bind:value={query}
    />
    {#if trimmed}
      {#if filtered.length}
        <div class="ip-grid">
          {#each filtered as name}
            <button
              type="button"
              class="ip-cell"
              class:on={value === name}
              title={name}
              aria-label={name}
              onclick={() => choose(name)}
            >
              <i class={`ti ti-${name}`} aria-hidden="true"></i>
            </button>
          {/each}
        </div>
      {:else}
        <p class="ip-empty">No icons match “{query}”.</p>
      {/if}
    {:else}
      {#each CURATED_ICON_CATEGORIES as category}
        <div class="ip-cat">
          <span class="ip-cat-label">{category.label}</span>
          <div class="ip-grid">
            {#each category.icons as name}
              <button
                type="button"
                class="ip-cell"
                class:on={value === name}
                title={name}
                aria-label={name}
                onclick={() => choose(name)}
              >
                <i class={`ti ti-${name}`} aria-hidden="true"></i>
              </button>
            {/each}
          </div>
        </div>
      {/each}
    {/if}
    <div class="ip-foot">
      <span class="ip-default">
        Default: <i class={`ti ti-${defaultGlyph}`} aria-hidden="true"></i> for this field type
      </span>
      <button type="button" class="ip-done" onclick={() => onClose?.()}>Done</button>
    </div>
  </div>
</div>

<style>
  .icon-picker {
    width: 264px;
    max-height: 340px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--border-strong);
    border-radius: 12px;
    background: var(--surface);
    box-shadow: var(--elev-2);
  }
  .ip-head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 12px;
    border-bottom: 1px solid var(--divider);
    background: var(--panel);
  }
  .ip-title {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-2);
  }
  .ip-field {
    color: var(--k-snippet-text);
  }
  .ip-reset {
    margin-left: auto;
    border: 0;
    background: transparent;
    font-size: var(--fs-xs);
    color: var(--text-3);
    cursor: pointer;
  }
  .ip-reset:hover {
    color: var(--accent);
    text-decoration: underline;
  }
  .ip-body {
    display: flex;
    flex-direction: column;
    gap: 9px;
    padding: 10px 12px;
    overflow: auto;
  }
  .ip-search {
    width: 100%;
    padding: 6px 9px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-md);
  }
  .ip-cat {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .ip-cat-label {
    font-size: var(--fs-xs);
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-3);
  }
  .ip-grid {
    display: grid;
    grid-template-columns: repeat(8, 1fr);
    gap: 6px;
  }
  .ip-cell {
    aspect-ratio: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--divider);
    border-radius: 8px;
    background: var(--surface);
    color: var(--text-2);
    font-size: var(--fs-xl);
    cursor: pointer;
  }
  .ip-cell:hover {
    border-color: var(--border-strong);
    background: var(--inset);
  }
  .ip-cell.on {
    background: var(--accent-soft);
    border-color: var(--accent);
    color: var(--accent-emphasis);
  }
  .ip-empty {
    margin: 4px 0;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  .ip-foot {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-top: 4px;
    border-top: 1px solid var(--divider);
    margin-top: 2px;
  }
  .ip-default {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .ip-done {
    margin-left: auto;
    padding: 4px 12px;
    border: 1px solid var(--accent);
    border-radius: 8px;
    background: var(--accent);
    color: #fff;
    font-size: var(--fs-sm);
    font-weight: 600;
    cursor: pointer;
  }
</style>
