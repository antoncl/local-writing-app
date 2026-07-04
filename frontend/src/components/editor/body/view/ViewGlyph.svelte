<!--
  Venn-diagram glyphs for the view designer's combinator nodes (ADR-0018): a
  two-circle icon with the *result region filled*, the Figma/Illustrator
  boolean-ops pattern. Difference fills only the left (keep) lobe so the
  surviving set is unmistakable — the confusable, non-commutative op (doc §1.2).
  Leaf / annotate / output kinds get a simple mono symbol instead.

  `uid` namespaces the clip/mask ids so multiple glyphs on one canvas don't
  collide.
-->
<script lang="ts">
  import type { GraphNodeKind } from "@/lib/views/viewGraph";

  interface Props {
    kind: GraphNodeKind;
    uid: string;
    size?: number;
  }
  let { kind, uid, size = 22 }: Props = $props();

  // Two circles: left (A / keep) and right (B / remove).
  const AX = 8.5;
  const BX = 13.5;
  const CY = 11;
  const R = 5.5;
</script>

{#if kind === "union" || kind === "intersect" || kind === "difference" || kind === "complement"}
  <svg class="glyph venn" width={size} height={size} viewBox="0 0 22 22" aria-hidden="true">
    {#if kind === "union"}
      <circle cx={AX} cy={CY} r={R} class="fill" />
      <circle cx={BX} cy={CY} r={R} class="fill" />
      <circle cx={AX} cy={CY} r={R} class="stroke" />
      <circle cx={BX} cy={CY} r={R} class="stroke" />
    {:else if kind === "intersect"}
      <clipPath id={`clip-a-${uid}`}><circle cx={AX} cy={CY} r={R} /></clipPath>
      <circle cx={BX} cy={CY} r={R} class="fill" clip-path={`url(#clip-a-${uid})`} />
      <circle cx={AX} cy={CY} r={R} class="stroke" />
      <circle cx={BX} cy={CY} r={R} class="stroke" />
    {:else if kind === "difference"}
      <!-- keep (left) lobe survives; overlap is punched out by masking B. -->
      <mask id={`mask-diff-${uid}`}>
        <rect x="0" y="0" width="22" height="22" fill="white" />
        <circle cx={BX} cy={CY} r={R} fill="black" />
      </mask>
      <circle cx={AX} cy={CY} r={R} class="fill" mask={`url(#mask-diff-${uid})`} />
      <circle cx={AX} cy={CY} r={R} class="stroke" />
      <circle cx={BX} cy={CY} r={R} class="stroke" />
    {:else if kind === "complement"}
      <!-- everything outside A within the frame. -->
      <mask id={`mask-comp-${uid}`}>
        <rect x="0" y="0" width="22" height="22" fill="white" />
        <circle cx={11} cy={CY} r={R} fill="black" />
      </mask>
      <rect x="1.5" y="1.5" width="19" height="19" rx="4" class="fill" mask={`url(#mask-comp-${uid})`} />
      <circle cx={11} cy={CY} r={R} class="stroke" />
    {/if}
  </svg>
{:else}
  <span class="glyph sym" style={`font-size:${size * 0.62}px`} aria-hidden="true">
    {#if kind === "type"}◆{:else if kind === "descendants_of"}⋔{:else if kind === "tagged"}#{:else if kind === "field"}=
    {:else if kind === "hand_picked"}✋{:else if kind === "view_ref"}⧉{:else if kind === "group"}▤{:else if kind === "highlight"}●
    {:else if kind === "output"}▶{:else}•{/if}
  </span>
{/if}

<style>
  .glyph {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
  }
  .venn .fill {
    /* Tint the *result region* with the accent at partial opacity rather than
       --accent-soft, which sits almost on top of the node background in both
       themes — making union (both lobes) and intersect (lens only) look
       identical because the distinguishing fill was invisible. */
    fill: var(--accent, #4361ee);
    fill-opacity: 0.3;
  }
  .venn .stroke {
    fill: none;
    stroke: var(--accent, #4361ee);
    stroke-width: 1.1;
  }
  .sym {
    color: var(--text-3, #6b7280);
    font-weight: 600;
  }
</style>
