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
  } = $props();
</script>

<div class="effective-body" class:snapshot={tone === "snapshot"} aria-label={label}>
  {#if ribbon}
    <div class="effective-body-ribbon">
      {#if ribbonMark}<span aria-hidden="true">{ribbonMark}</span>{/if}
      {ribbon}
    </div>
  {/if}
  <div class="effective-body-content">
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

     **The edge rule is not decoration.** Roughly 1 in 12 men has a colour-vision
     deficiency and warm-vs-cool is the axis most affected, so hue must never be
     the only channel: an underline survives greyscale where a wash does not
     (§H). It bites hardest in the light theme, whose chroma is halved.

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
    background: var(--diff-was-soft);
    box-shadow: inset 0 -2px 0 var(--diff-was-edge);
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
    background: var(--diff-was-soft);
  }
  .effective-body-content :global(.blk p:last-child) {
    margin-bottom: 0;
  }
</style>
