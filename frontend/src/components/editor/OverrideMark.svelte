<script lang="ts">
  // The interactive override tell (#517 / ADR-0039), extracted from
  // RailFieldRow so #2184 slice 3 can reuse it verbatim for the title and
  // body marks, which have no rail row: the `ti-versions` glyph in the
  // `--star` tint, doubling as the reset control. Hover/focus reveals a
  // "Reset to <source>" chip above the mark; the button itself is the tab
  // stop (`:focus-visible` also shows the chip), so the reset is never
  // hover-only.
  interface Props {
    // The chip's label, e.g. "Reset to Aetheria" / "Reset to Aetheria…".
    chipText: string;
    // The button's `title` tooltip.
    tooltip: string;
    ariaLabel: string;
    onReset: () => void;
    testid?: string;
  }

  let { chipText, tooltip, ariaLabel, onReset, testid }: Props = $props();
</script>

<button
  type="button"
  class="override-mark"
  title={tooltip}
  aria-label={ariaLabel}
  data-testid={testid}
  onclick={onReset}
>
  <i class="ti ti-versions" aria-hidden="true"></i>
  <span class="override-mark-chip"><i class="ti ti-arrow-back-up" aria-hidden="true"></i>{chipText}</span>
</button>

<style>
  /* Same visual language as RailFieldRow's `button.fr-override-marker.fr-reset`
     — kept byte-for-byte equivalent (not shared via a class export) so this
     component stays a standalone, droppable widget. */
  .override-mark {
    display: inline-flex;
    align-items: center;
    position: relative;
    padding: 0;
    border: 0;
    background: none;
    cursor: pointer;
    color: var(--star);
    font-size: var(--fs-md);
    line-height: 1;
  }
  .override-mark:focus-visible {
    outline: 2px solid var(--star);
    outline-offset: 2px;
    border-radius: var(--r-sm);
  }
  .override-mark-chip {
    display: none;
    position: absolute;
    bottom: 100%;
    left: 0;
    margin-bottom: 3px;
    align-items: center;
    gap: 3px;
    padding: 2px 8px;
    background: var(--surface);
    border: 1px solid var(--border-strong);
    box-shadow: var(--elev-2);
    border-radius: var(--r-md);
    font-size: var(--fs-xs);
    color: var(--star);
    white-space: nowrap;
    z-index: 6;
  }
  .override-mark:hover .override-mark-chip,
  .override-mark:focus-visible .override-mark-chip {
    display: inline-flex;
  }
</style>
