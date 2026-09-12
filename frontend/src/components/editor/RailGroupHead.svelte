<script lang="ts">
  // The one L1 group header (#1884 slice 3) — used by both the MetadataPanel
  // rail (foldable, `onToggle` supplied) and SchemaTypeEditor (non-foldable,
  // "define looks like display"). Previously each host duplicated the same
  // label+rule markup against global CSS in styles.css; that markup + the CSS
  // now live here as one atom, and the rail additionally gets a caret so each
  // L1 block can fold.
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";

  let { label, expanded = true, onToggle = undefined }: { label: string; expanded?: boolean; onToggle?: () => void } = $props();
</script>

<div class="rail-group-head" class:foldable={!!onToggle}>
  {#if onToggle}
    <button type="button" class="rgh-toggle" aria-expanded={expanded}
      aria-label={expanded ? `Collapse ${label}` : `Expand ${label}`}
      title={expanded ? "Collapse" : "Expand"} onclick={onToggle}>
      <GroupCaret size="xs" collapsed={!expanded} />
      <span class="rail-group-label">{label}</span>
    </button>
  {:else}
    <span class="rgh-gutter" aria-hidden="true"></span>
    <span class="rail-group-label">{label}</span>
  {/if}
  <span class="rail-group-rule"></span>
</div>

<style>
  /* L1 group section header — shared between the MetadataPanel rail and the
     type editor's field list. "Define looks like display." Padding
     matches the per-row horizontal padding used by both .field-row and
     .schema-field-row. */
  .rail-group-head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 12px 4px;
  }
  .rail-group-label {
    font-size: var(--fs-xs);
    font-weight: var(--w-semibold);
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-3, var(--text-3));
  }
  .rail-group-rule {
    flex: 1;
    height: 1px;
    background: var(--divider, var(--divider));
  }

  /* Foldable (rail) toggle: caret + label share the disclosure column. The
     `size="xs"` GroupCaret glyph is a 15px slot (not the 22px `.fr-disc`
     column a field row reserves), so the gap is widened rather than left at
     the field row's 10px — 12 (row padding) + 15 (caret) + 17 (gap) = 44,
     the same x where a field row's `.fr-icon` starts (12 + 22 + 10). */
  .rgh-toggle { display: inline-flex; align-items: center; gap: 17px; padding: 0; border: none; background: none; color: inherit; font: inherit; cursor: pointer; }
  .rgh-toggle:hover .rail-group-label { color: var(--text); }
  .rgh-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: var(--r-sm); }
  /* Non-foldable (type editor): a plain 22px spacer stands in for the caret so
     the label still lands close to the field glyph column. */
  .rgh-gutter { flex: none; width: 22px; }
</style>
