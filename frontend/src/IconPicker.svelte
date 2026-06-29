<script lang="ts">
  import { CURATED_ICON_CATEGORIES, CURATED_ICONS } from "./fieldIcons";

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
    border: 1px solid var(--border-strong, #b4c2bc);
    border-radius: 12px;
    background: var(--surface, #fff);
    box-shadow: 0 10px 30px rgba(20, 40, 35, 0.18);
  }
  .ip-head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 9px 12px;
    border-bottom: 1px solid var(--divider, #e2e8e5);
    background: var(--panel, #edf3f1);
  }
  .ip-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-2, #4d5753);
  }
  .ip-field {
    color: var(--k-snippet-text, #7a5230);
  }
  .ip-reset {
    margin-left: auto;
    border: 0;
    background: transparent;
    font-size: 11px;
    color: var(--text-3, #74817b);
    cursor: pointer;
  }
  .ip-reset:hover {
    color: var(--accent, #2f6f5e);
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
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 8px;
    background: var(--surface, #fff);
    font-size: 13px;
  }
  .ip-cat {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .ip-cat-label {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--text-3, #74817b);
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
    border: 1px solid var(--divider, #e2e8e5);
    border-radius: 8px;
    background: var(--surface, #fff);
    color: var(--text-2, #4d5753);
    font-size: 16px;
    cursor: pointer;
  }
  .ip-cell:hover {
    border-color: var(--border-strong, #b4c2bc);
    background: var(--inset, #f1f5f3);
  }
  .ip-cell.on {
    background: var(--accent-soft, #edf6f2);
    border-color: var(--accent, #2f6f5e);
    color: var(--accent-strong, #234e43);
  }
  .ip-empty {
    margin: 4px 0;
    font-size: 12px;
    color: var(--text-3, #74817b);
  }
  .ip-foot {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-top: 4px;
    border-top: 1px solid var(--divider, #e2e8e5);
    margin-top: 2px;
  }
  .ip-default {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 11px;
    color: var(--text-3, #74817b);
  }
  .ip-done {
    margin-left: auto;
    padding: 4px 12px;
    border: 1px solid var(--accent, #2f6f5e);
    border-radius: 8px;
    background: var(--accent, #2f6f5e);
    color: #fff;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
</style>
