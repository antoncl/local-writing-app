<script lang="ts">
  // A read-only rendered-markdown body, laid over the editor while the pane is
  // showing some state other than the live one (#64 the mutation scrub, #401
  // the snapshot strip).
  //
  // **The editable TipTap buffer stays mounted and hidden underneath** — the
  // host only sets `display: none` on its wrapper — so unsaved edits survive
  // the round trip untouched. That is the point of the mechanism rather than a
  // detail of it: the buffer is never touched by the features whose job is not
  // losing words, and rendered HTML makes layouts that are near-intractable as
  // ProseMirror decorations trivial (ADR-0044 §G).
  //
  // Extracted from NodeEditor when snapshots became the second consumer. One
  // overlay, two axes; the ribbon's tone is the only thing that differs.
  let {
    html,
    label,
    ribbon = "",
    ribbonMark = "",
    tone = "mutation",
    onRunClick,
  }: {
    html: string;
    label: string;
    /** Optional banner above the body, naming what is being shown. */
    ribbon?: string;
    /** A glyph for the ribbon — annotation only; the overlay never adds an
     *  affordance mark (design language: a mark is never both). */
    ribbonMark?: string;
    /** Which axis this overlay belongs to, which is all the colour means. */
    tone?: "mutation" | "snapshot";
    /** When set, changed runs become clickable to adopt one region while parked
     *  (ADR-0044 Amendment 4). No glyph is added — the run's own colour is the
     *  affordance (§J) — and this is a pointer gesture only, so the compare
     *  view's whole keyboard stays free for A/S/B (§I). */
    onRunClick?: (regionId: number, kind: "now" | "was") => void;
  } = $props();

  let contentEl: HTMLElement | undefined = $state();

  /** A click on the rendered HTML: find the run the author hit and hand its
   *  region + side up. */
  function handleRunClick(event: MouseEvent): void {
    if (!onRunClick) return;
    const hit = (event.target as HTMLElement | null)?.closest?.("[data-region]") as HTMLElement | null;
    if (!hit) return;
    const regionId = Number(hit.dataset.region);
    if (!Number.isInteger(regionId)) return;
    const kind = hit.classList.contains("r-was") || hit.classList.contains("blk-was")
      ? "was"
      : hit.classList.contains("r-now") || hit.classList.contains("blk-now")
        ? "now"
        : null;
    if (kind) onRunClick(regionId, kind);
  }

  // Delegated because the runs come from `{@html}` — there is nothing to bind a
  // handler to per run — and attached imperatively so the static container needs
  // no interactive ARIA role. It is a pointer gesture only: adopting takes no
  // key, so A/S/B and the arrows stay free (ADR-0044 §I).
  $effect(() => {
    const el = contentEl;
    if (!el || !onRunClick) return;
    el.addEventListener("click", handleRunClick);
    return () => el.removeEventListener("click", handleRunClick);
  });
</script>

<div
  class="effective-body"
  class:snapshot={tone === "snapshot"}
  class:interactive={!!onRunClick}
  aria-label={label}
>
  {#if ribbon}
    <div class="effective-body-ribbon">
      {#if ribbonMark}<span aria-hidden="true">{ribbonMark}</span>{/if}
      {ribbon}
    </div>
  {/if}
  <div class="effective-body-content" bind:this={contentEl}>
    <!-- eslint-disable-next-line svelte/no-at-html-tags — sceneMarkdownToHtml output, same trust level as the editor load path -->
    {@html html}
  </div>
</div>

<style>
  .effective-body {
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    --overlay-tone: var(--mutation-color);
  }
  .effective-body.snapshot {
    --overlay-tone: var(--diff-was);
  }
  .effective-body-ribbon {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 24px;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--overlay-tone);
    background: color-mix(in srgb, var(--overlay-tone) 10%, transparent);
    border-bottom: 1px solid color-mix(in srgb, var(--overlay-tone) 30%, transparent);
  }
  .effective-body-content {
    padding: 12px 24px 24px;
    max-width: 72ch;
    font-size: var(--fs-lg);
    line-height: 1.65;
    color: var(--text);
  }
  .effective-body-content :global(p) {
    margin: 0 0 0.9em;
  }

  /* ---- The diff tint (ADR-0044 §F/§H, #409) --------------------------------
     Warm = in the scene NOW, cool = in the SNAPSHOT. One rule, and the three
     cases fall out of it: an addition is warm because it exists only in the
     current scene, a deletion is cool because it exists only in the snapshot,
     and a modification is simply the two adjacent.

     The tint stays in EVERY compare state, not only Both. With nothing marked,
     a flip changes words somewhere and the eye has no anchor — the tint is what
     holds your place while the words swap underneath it.

     **The edge rule is not decoration, and its SHAPE is the load-bearing part.**
     Roughly 1 in 12 men has a colour-vision deficiency and warm-vs-cool is the
     axis most affected, so hue must never be the only channel (§H).

     Colour alone cannot carry that here, and the reason is structural rather
     than a badly chosen swatch: §H also requires equal chroma across the pair
     within a theme, so neither reads as more important — and equal chroma at
     equal lightness is equal LUMINANCE, which is exactly what greyscale keeps.
     Measured on the shipped tokens the two washes differ by 0.1 of 255 in light
     and 2.1 in dark: indistinguishable, by construction.

     Separating the edges by lightness instead would work, and trade the problem
     for the one §H was avoiding — a darker rule on one side reads as heavier,
     which is unequal weight moved from the chroma channel into the lightness
     one. So the edges differ by **shape**: solid for the scene now, dotted for
     the snapshot. Shape is neither hue nor lightness, so equal chroma and equal
     weight both survive and greyscale keeps the distinction whole. The archived
     side reading as the provisional one is the right way round.

     Drawn as a background gradient rather than a border so it costs no layout —
     a 2px border on an inline span would move the line box under the prose.

     `:global` because this HTML comes from `{@html}` and Svelte's scoping never
     sees it. The class names are the runs' own (`diffRuns.ts`). */
  .effective-body-content :global(.r-now),
  .effective-body-content :global(.r-was) {
    border-radius: var(--r-sm);
    padding: 0.06em 0.22em;
  }
  .effective-body-content :global(.r-now) {
    background: var(--diff-now-soft);
    box-shadow: inset 0 -2px 0 var(--diff-now-edge);
  }
  .effective-body-content :global(.r-was) {
    background-color: var(--diff-was-soft);
    background-image: repeating-linear-gradient(
      to right,
      var(--diff-was-edge) 0 3px,
      transparent 3px 6px
    );
    background-repeat: no-repeat;
    background-position: 0 100%;
    background-size: 100% 2px;
  }

  /* A change spanning block boundaries stacks — no inline element can wrap two
     paragraphs, so the wrapper goes around the RENDERED output instead. This is
     structural and never a length threshold: a word count deciding the layout
     would make it jitter as the author types (§F). */
  .effective-body-content :global(.blk) {
    display: block;
    border-left: 3px solid transparent;
    padding: 0.35em 0 0.35em 0.7em;
    margin: 0 0 0.5em;
    border-radius: 0 var(--r-sm) var(--r-sm) 0;
  }
  .effective-body-content :global(.blk-now) {
    border-left-color: var(--diff-now);
    background: var(--diff-now-soft);
  }
  .effective-body-content :global(.blk-was) {
    border-left-color: var(--diff-was);
    border-left-style: dashed;
    background: var(--diff-was-soft);
  }
  .effective-body-content :global(.blk p:last-child) {
    margin-bottom: 0;
  }

  /* ---- Adopting a region (ADR-0044 Amendment 4, #419) ----------------------
     Only when the overlay is interactive. The colour is already the affordance
     (§J adds no glyph); hover only firms the edge of the run under the cursor —
     the warm side deepens its wash, the cool side trades its dotted rule for a
     solid one — so the target reads without a new mark. Pointer-only (§I). */
  .effective-body.interactive :global(.r-now),
  .effective-body.interactive :global(.r-was),
  .effective-body.interactive :global(.blk-now),
  .effective-body.interactive :global(.blk-was) {
    cursor: pointer;
  }
  .effective-body.interactive :global(.r-now:hover) {
    background: var(--diff-now-edge);
  }
  .effective-body.interactive :global(.r-was:hover) {
    box-shadow: inset 0 -2px 0 var(--diff-was);
  }
  .effective-body.interactive :global(.blk-now:hover) {
    border-left-width: 5px;
  }
  .effective-body.interactive :global(.blk-was:hover) {
    border-left-style: solid;
    border-left-width: 5px;
  }
</style>
