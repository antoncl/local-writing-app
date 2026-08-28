<script lang="ts">
  // Disclosure caret for group-header rows (rendered into a NodeRow leading
  // slot across the lore/prompts/assistants/tree/backlinks/reference surfaces).
  // Decorative glyph — always aria-hidden. A real chevron (not an 11px text
  // glyph) sized into a fixed slot so it reads at a glance and every row that
  // hosts one reserves one caret gutter (ADR-0066 Amendment 1). Points down
  // when expanded, right when collapsed.
  //
  // Sizes are the slot (hit-box), not the glyph: `sm`/`md` (22/24px) are row
  // hit-targets; `xs` (15px) is for a decorative trailing indicator — an
  // "opens a menu" ▾ — where the control itself is the tap target, so the
  // chevron shouldn't carry a hit-target's footprint. The glyph stays 13px.
  interface Props {
    collapsed?: boolean;
    size?: "xs" | "sm" | "md";
  }

  let { collapsed = false, size = "sm" }: Props = $props();
</script>

<span
  class="caret"
  class:collapsed
  class:xs={size === "xs"}
  class:md={size === "md"}
  aria-hidden="true"
>
  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path
      d="M8 5l8 7-8 7"
      stroke="currentColor"
      stroke-width="2.4"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
</span>

<style>
  .caret {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    color: var(--text-3);
  }

  .caret svg {
    width: 13px;
    height: 13px;
    /* Path points right by default; rotate to point down when expanded. */
    transform: rotate(90deg);
    transition: transform 120ms ease;
  }

  .caret.collapsed svg {
    transform: rotate(0deg);
  }

  .caret.md {
    width: 24px;
    height: 24px;
    color: var(--text-2);
  }

  .caret.md svg {
    width: 14px;
    height: 14px;
  }

  /* Decorative trailing indicator: shrink the slot to the glyph, no hit-box. */
  .caret.xs {
    width: 15px;
    height: 15px;
  }
</style>
