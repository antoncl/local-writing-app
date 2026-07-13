<!--
  Custom Svelte Flow edge for a recursion self-loop (a Nest node's output wired
  back into its own `parents` handle, ADR-0028 §D). Source and target sit on the
  same node, so a default bezier cuts back across the node body and hides behind
  it. We route an orthogonal (step) path instead: out past the source handle, up
  above the node, across, and down into the target handle. Clearance is uniform —
  the top leg sits `REACH` above the node's top edge, the same gap the side legs
  keep from the (handle-bearing) side edges — so the loop frames the node evenly.
  Corners are rounded for a smoothstep look.
-->
<script lang="ts">
  import { BaseEdge, useSvelteFlow } from "@xyflow/svelte";

  let {
    source,
    sourceX,
    sourceY,
    targetX,
    targetY,
    markerEnd,
    style,
  }: {
    source: string;
    sourceX: number;
    sourceY: number;
    targetX: number;
    targetY: number;
    markerEnd?: string;
    style?: string;
  } = $props();

  const REACH = 46; // uniform gap between the loop and every node edge
  const RADIUS = 12; // corner rounding

  // Source and target are the same node; its top edge gives the vertical gap so
  // it matches the horizontal one (the handles already sit on the side edges).
  const { getInternalNode } = useSvelteFlow();

  // Build a rounded orthogonal path through a list of axis-aligned corners.
  function roundedPath(points: [number, number][]): string {
    if (points.length < 2) return "";
    let d = `M ${points[0][0]},${points[0][1]}`;
    for (let i = 1; i < points.length - 1; i++) {
      const [px, py] = points[i - 1];
      const [x, y] = points[i];
      const [nx, ny] = points[i + 1];
      const inLen = Math.hypot(x - px, y - py) || 1;
      const outLen = Math.hypot(nx - x, ny - y) || 1;
      const r = Math.min(RADIUS, inLen / 2, outLen / 2);
      const entryX = x - ((x - px) / inLen) * r;
      const entryY = y - ((y - py) / inLen) * r;
      const exitX = x + ((nx - x) / outLen) * r;
      const exitY = y + ((ny - y) / outLen) * r;
      d += ` L ${entryX},${entryY} Q ${x},${y} ${exitX},${exitY}`;
    }
    const last = points[points.length - 1];
    d += ` L ${last[0]},${last[1]}`;
    return d;
  }

  let path = $derived.by(() => {
    const rightX = sourceX + REACH;
    const leftX = targetX - REACH;
    const nodeTop = getInternalNode(source)?.internals.positionAbsolute.y;
    // Uniform gap above the node top; fall back to a handle-relative crest
    // before the node has been measured.
    const crestY = nodeTop !== undefined ? nodeTop - REACH : Math.min(sourceY, targetY) - REACH;
    return roundedPath([
      [sourceX, sourceY],
      [rightX, sourceY],
      [rightX, crestY],
      [leftX, crestY],
      [leftX, targetY],
      [targetX, targetY],
    ]);
  });
</script>

<!-- The self-loop is always a Nest recursion (output → own `parents`), so it
     carries the lore slate-blue of the children port it pairs with (§240). -->
<BaseEdge {path} {markerEnd} style={`${style ?? ""}; stroke: var(--k-lore); stroke-opacity: 0.7;`} />
