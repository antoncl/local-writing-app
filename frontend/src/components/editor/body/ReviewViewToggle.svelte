<!--
  ReviewViewToggle (#2561) - the A / S / B version control of an edit review bar:
  read the passages as the page's own words (Current), as if every edit were
  accepted (Proposed), or as the diff (Both). The same views as
  Alt+A / Alt+S / Alt+B in the editor; the plugin owns the state.

  A thin adapter over the shared SegmentedControl (#2530), so every review's
  version switcher is one widget. mousedown preventDefault (on the wrapper)
  keeps the editor focused.
-->
<script lang="ts">
  import SegmentedControl from "@/components/widgets/SegmentedControl.svelte";
  import type { ReviewView } from "@/lib/editor-core/lineEditSuggestions";

  interface Props {
    view: ReviewView;
    onView: (view: ReviewView) => void;
  }

  let { view, onView }: Props = $props();

  const VIEWS = [
    { id: "now", label: "Current", key: "A", hint: "the passage as it is now", tone: "warm" },
    { id: "proposed", label: "Proposed", key: "S", hint: "the passage with every edit applied", tone: "cool" },
    { id: "both", label: "Both", key: "B", hint: "both versions, marked" },
  ] as const;

  const keepFocus = (e: MouseEvent) => e.preventDefault();
</script>

<span class="rvt" role="presentation" onmousedown={keepFocus}>
  <SegmentedControl items={VIEWS} value={view} ariaLabel="Version shown" keyModifier="Alt+" onSelect={onView} />
</span>

<style>
  .rvt {
    flex: none;
    display: inline-flex;
  }
</style>
