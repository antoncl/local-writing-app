// A single shared offscreen canvas for measuring text width without laying it
// out. One canvas serves every caller: `ctx.font` is set per call and
// `measureText` is synchronous, so instances never interfere. Returns 0 when
// there is no DOM / 2D context (SSR, or a test environment without canvas),
// which callers treat as "unmeasured".

let sharedCanvas: HTMLCanvasElement | null = null;

export function measureTextWidth(text: string, font: string): number {
  if (typeof document === "undefined") return 0;
  if (!sharedCanvas) sharedCanvas = document.createElement("canvas");
  const ctx = sharedCanvas.getContext("2d");
  if (!ctx) return 0;
  ctx.font = font;
  return ctx.measureText(text).width;
}
