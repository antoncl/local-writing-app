<script lang="ts">
  // The pending-brainstorm-review marker (#710 slice 3). A quiet dot in the
  // chat/graphite kind colour — the same 7px geometry as the cost / journal-fresh
  // dots — shown on an entry's workspace tab and its roster row while an AI
  // revision waits to be reviewed. Colour, not a glyph, and no competing word: it
  // reads as "a revision from that chat is waiting" and clears itself the moment
  // the review is committed or discarded (its callers read entryBrainstorm).
  // One home so the tab and the roster can't drift apart.
</script>

<span class="review-dot" title="A brainstorm revision is ready to review" aria-label="Review pending"></span>

<style>
  .review-dot {
    flex: none;
    display: inline-block;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--k-graphite);
  }
</style>
