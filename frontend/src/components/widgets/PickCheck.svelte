<script module lang="ts">
  // PickCheck — the tri-state pick checkbox visual for a context-picker row
  // (ADR-0074 slice 7a). Purely decorative: it is `aria-hidden`, and the row's
  // NodeRow title button carries the real semantics (`aria-pressed` + an sr-only
  // state word). Rendered in NodeRow's `leading` slot so every pickable row —
  // container or leaf, any source — shows the same 16px box.
  //
  // States:
  //   on            — explicitly picked (filled accent + ✓)
  //   family        — picked WITH its subtypes (filled accent + ✓ over a stacked
  //                   card), the author-time tri-state's third step (#1947); the
  //                   runtime picker never sets it
  //   implied       — included via a checked container (soft fill + ✓)
  //   indeterminate — a container with only some descendants picked (centre square)
  //   off           — not picked (bare border)
  export type PickCheckState = "on" | "family" | "implied" | "indeterminate" | "off";
</script>

<script lang="ts">
  const { state }: { state: PickCheckState } = $props();
</script>

<span class={`pick-check pick-check-${state}`} aria-hidden="true"
  >{state === "on" || state === "family" || state === "implied" ? "✓" : ""}</span
>

<style>
  .pick-check {
    flex: none;
    width: 16px;
    height: 16px;
    border: 1.5px solid var(--border);
    border-radius: 4px;
    background: var(--surface);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: var(--fs-xs);
    line-height: 1;
    color: transparent;
    position: relative;
  }
  .pick-check-on {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--surface);
  }
  /* Family (this type + subtypes): the filled `on` box over a quiet stacked
     card, so "and everything under it" reads at a glance without a second glyph
     fighting for room in 16px. The offset box-shadow is the card peeking out
     bottom-right. */
  .pick-check-family {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--surface);
    box-shadow: 2.5px 2.5px 0 -0.5px var(--accent-soft2);
  }
  .pick-check-implied {
    background: var(--accent-soft2);
    border-color: var(--accent);
    color: var(--accent-emphasis);
  }
  .pick-check-indeterminate {
    border-color: var(--accent);
  }
  .pick-check-indeterminate::after {
    content: "";
    position: absolute;
    inset: 4px;
    background: var(--accent);
    border-radius: 1px;
  }
</style>
