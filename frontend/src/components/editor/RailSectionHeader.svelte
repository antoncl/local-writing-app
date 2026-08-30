<script lang="ts">
  // One collapsible section header for the metadata rail (#1438). Replaces the
  // three divergent implementations the rail grew — References borrowed a
  // NodeRow group header (sans --fs-lg 700 --text-2), while Conversations and
  // Mutation sets each rolled a bespoke serif-700 header. None matched the
  // inline field rows, so four label recipes shared one narrow column.
  //
  // The rail's one row grammar (design-language §3.5): every line reads
  // `‹disclosure› ‹glyph› ‹name› … ‹trailing›`, and the disclosure + glyph
  // columns line up with MetadataPanel's field rows so every glyph sits on one
  // vertical line down the rail. Name typography is the field-row recipe: sans
  // --fs-md --w-medium --text — quiet tool text, never serif.
  //
  // Why not NodeRow (the reason Conversations/Mutation sets forked it): NodeRow styles
  // every <button> in its trailing slot as a fixed-size icon tile, which flattens
  // a worded "＋ New" menu button. Here the trailing slot is a plain snippet — the
  // caller supplies count + action styled however it likes. The row LISTS still
  // render through NodeRow/ViewNodeList; only this header is bespoke chrome.
  import type { Snippet } from "svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import CountPill from "@/components/widgets/CountPill.svelte";

  let {
    title,
    // Full Tabler class name, e.g. "ti-link". Rendered as `ti <glyph>`.
    glyph,
    count = null,
    expanded = false,
    onToggle,
    // Optional right-side affordance (e.g. a ＋New menu button). Rendered
    // OUTSIDE the toggle button so it can be interactive — no icon-tile styling.
    trailing = undefined,
  }: {
    title: string;
    glyph: string;
    count?: number | null;
    expanded?: boolean;
    onToggle: () => void;
    trailing?: Snippet;
  } = $props();
</script>

<div class="rail-section-header">
  <button type="button" class="rsh-toggle" aria-expanded={expanded} onclick={onToggle}>
    <GroupCaret collapsed={!expanded} />
    <span class="rsh-glyph"><i class="ti {glyph}" aria-hidden="true"></i></span>
    <span class="rsh-name">{title}</span>
    {#if count !== null}<CountPill {count} />{/if}
  </button>
  {#if trailing}<span class="rsh-trailing">{@render trailing()}</span>{/if}
</div>

<style>
  .rail-section-header {
    display: flex;
    align-items: center;
    gap: 8px;
    border-bottom: 1px solid var(--divider);
    padding-bottom: 4px;
    margin-bottom: 6px;
  }

  /* The toggle spans caret · glyph · name · count. Its left padding (12) + the
     caret (22) + gap (10) put the glyph at the same x as a MetadataPanel field
     row's glyph (padding 12 + disclosure spacer 22 + gap 10), so section and
     field glyphs share one vertical line. */
  .rsh-toggle {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 12px;
    border: none;
    border-radius: var(--r-sm);
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .rsh-toggle:hover {
    background: var(--accent-soft);
  }

  .rsh-glyph {
    flex: none;
    width: 24px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--text-2);
    font-size: var(--fs-md);
  }

  /* The one rail-row name recipe — matches MetadataPanel `.fr-name`. */
  .rsh-name {
    flex: 1 1 auto;
    min-width: 0;
    font-family: var(--sans);
    font-size: var(--fs-md);
    font-weight: var(--w-medium);
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .rsh-trailing {
    flex: none;
    display: inline-flex;
    align-items: center;
  }
</style>
