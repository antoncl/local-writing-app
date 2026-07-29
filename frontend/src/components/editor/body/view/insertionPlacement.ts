// Insertion placement (ADR-0038 §E) — the coordinate math behind palette
// drops and click-inserts, extracted from ViewBodyView (size cap).
//
// The equivalent of SvelteFlow's `screenToFlowPosition`, hand-rolled (not the
// real call — the drop target is the wrapper div, outside the flow provider
// context `useSvelteFlow()` needs): invert the live viewport transform (read
// off the DOM — `bind:viewport` only emits on a viewport CHANGE, so it stays
// undefined until the first pan/zoom) against the canvas rect. Drop lands
// under the pointer; click lands at the viewport centre (killing the old
// top-left staircase).

export const DND_MIME = "application/x-view-node-kind";

type XY = { x: number; y: number };

function readViewport(canvasEl: HTMLElement | undefined): { x: number; y: number; zoom: number } | null {
  const t = canvasEl?.querySelector<HTMLElement>(".svelte-flow__viewport")?.style.transform;
  const m = t ? /translate\(\s*(-?[\d.]+)px,\s*(-?[\d.]+)px\)\s*scale\(\s*([\d.]+)\s*\)/.exec(t) : null;
  return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]), zoom: parseFloat(m[3]) } : null;
}

function staircaseFallback(nodeCount: number): XY {
  return { x: 60, y: 60 + (nodeCount % 8) * 46 };
}

export function toFlowPos(canvasEl: HTMLElement | undefined, nodeCount: number, clientX: number, clientY: number): XY {
  const rect = canvasEl?.getBoundingClientRect();
  const vp = readViewport(canvasEl);
  if (!rect || !vp) return staircaseFallback(nodeCount);
  return { x: (clientX - rect.left - vp.x) / vp.zoom, y: (clientY - rect.top - vp.y) / vp.zoom };
}

export function centrePos(canvasEl: HTMLElement | undefined, nodeCount: number): XY {
  const rect = canvasEl?.getBoundingClientRect();
  const vp = readViewport(canvasEl);
  if (!rect || !vp) return staircaseFallback(nodeCount);
  // Nudge by roughly half a compact node so it reads as centred, not corner-hung.
  return { x: (rect.width / 2 - vp.x) / vp.zoom - 55, y: (rect.height / 2 - vp.y) / vp.zoom - 20 };
}
