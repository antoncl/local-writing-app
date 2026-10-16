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
    frontMatter = undefined,
    appendix = undefined,
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
    /** Front matter / appendix (#2054): the rail's facts and trailing material
     *  as document blocks while the rail is collapsed — the same blocks the
     *  live prose frame renders, so the facts stay with the document in every
     *  lens (read-only here, like the rail would be). */
    frontMatter?: import("svelte").Snippet;
    appendix?: import("svelte").Snippet;
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
  {#if frontMatter}
    <div class="effective-front-matter prose-column" data-testid="overlay-front-matter">{@render frontMatter()}</div>
  {/if}
  <div class="effective-body-content prose-column" bind:this={contentEl}>
    <!-- eslint-disable-next-line svelte/no-at-html-tags — sceneMarkdownToHtml output, same trust level as the editor load path -->
    {@html html}
  </div>
  {#if appendix}
    <div class="effective-appendix prose-column" data-testid="overlay-appendix">{@render appendix()}</div>
  {/if}
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
  /* The column (measure, gutter, font) is the live editor's own `.prose-column`
     rule (#2051), so scrubbing / parking a snapshot never jumps the column
     width, position or type size (#1246). */
  .effective-body-content {
    padding-block: 12px 24px;
    line-height: 1.65;
    color: var(--text);
  }
  .effective-front-matter {
    padding-top: 4px;
  }
  .effective-appendix {
    padding-bottom: 24px;
  }
  /* Mirror the editor's prose-presentation prefs (#127 / #575) so the scrub /
     snapshot overlay never diverges from the live surface. Scoped to direct
     children (like `.editor-body > p`) so table-cell and blockquote paragraphs
     are excluded, with the same table-cell reset the editor applies. */
  .effective-body-content > :global(p) {
    margin: 0 0 var(--prose-para-gap, 0.9em);
    text-align: var(--prose-align, left);
    text-indent: var(--prose-indent, 0);
  }
  .effective-body-content :global(td p),
  .effective-body-content :global(th p) {
    margin: 0;
    text-align: left;
    text-indent: 0;
  }

  /* The diff tint itself (`.r-now` / `.r-was`) is global, in styles.css: line
     edits (ADR-0100 §11) wear the same look. Only the interactive rules live here. */

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
  /* No width change — the 3px gutter is already reserved, so firming it must not
     reflow the block's text. The warm side deepens its wash like an inline run;
     the cool side trades dashed for solid at the same width. */
  .effective-body.interactive :global(.blk-now:hover) {
    background: var(--diff-now-edge);
  }
  .effective-body.interactive :global(.blk-was:hover) {
    border-left-style: solid;
  }
</style>
