<!--
  ReviewViewToggle (#2561) - the A / S / B version control of an edit review bar:
  read the passages as the page's own words (Current), as if every edit were
  accepted (Proposed), or as the diff (Both). The same views as
  Alt+A / Alt+S / Alt+B in the editor; the plugin owns the state.

  Pure presentation. mousedown preventDefault keeps the editor focused.
-->
<script lang="ts">
  import type { ReviewView } from "@/lib/editor-core/lineEditSuggestions";

  interface Props {
    view: ReviewView;
    onView: (view: ReviewView) => void;
  }

  let { view, onView }: Props = $props();

  const VIEWS = [
    { id: "now", label: "Current", key: "A", hint: "the passage as it is now" },
    { id: "proposed", label: "Proposed", key: "S", hint: "the passage with every edit applied" },
    { id: "both", label: "Both", key: "B", hint: "both versions, marked" },
  ] as const;

  const keepFocus = (e: MouseEvent) => e.preventDefault();
</script>

<span class="rvt" role="group" aria-label="Version shown">
  {#each VIEWS as v (v.id)}
    <button
      type="button"
      class="rvt-btn"
      class:active={view === v.id}
      data-testid="review-view-{v.id}"
      aria-pressed={view === v.id}
      title="{v.label}: {v.hint} (Alt+{v.key})"
      onmousedown={keepFocus}
      onclick={() => onView(v.id)}
    ><kbd>{v.key}</kbd> {v.label}</button>
  {/each}
</span>

<style>
  .rvt {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 2px;
  }

  .rvt-btn {
    flex: none;
    background: transparent;
    border: none;
    color: var(--text-2);
    padding: 4px 8px;
    font-size: var(--fs-sm);
    line-height: 1;
    border-radius: 4px;
    cursor: pointer;
  }

  .rvt-btn kbd {
    font: inherit;
    color: var(--text-3);
  }

  .rvt-btn:hover {
    background: var(--inset);
    color: var(--text);
  }

  .rvt-btn.active {
    background: var(--inset);
    color: var(--text);
  }
</style>
