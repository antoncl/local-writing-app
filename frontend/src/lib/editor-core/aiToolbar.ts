// Shared types for ProseBodyView's floating AI inline toolbar.
// The host (the AI-suggestion pipeline) owns the generation/suggestion state
// and where the toolbar shows (aiToolbarPosition); the presentational
// ProseAIToolbar component renders the status / accept-retry-discard controls
// and the usage-cost meta from these.

import type { ChatUsage } from "@/lib/types";

// `placement` is where the toolbar sits relative to the suggestion's first
// line: "above" (the default — lifted clear of the prose) or "below" (the
// flip used when the suggestion starts too near the top of the scroll content
// for the toolbar to fit above without being clipped). `y` is the content-space
// anchor edge for that placement — the line's top when above, its bottom when
// below. Absent placement is treated as "above" (only the hidden reset states
// omit it, where it doesn't matter).
export type AiToolbarPosition = {
  x: number;
  y: number;
  visible: boolean;
  placement?: "above" | "below";
};

// Room a one-row toolbar + gap needs above its anchor line before it flips below.
const TOOLBAR_CLEARANCE = 40;

// Where the AI toolbar goes for an anchor line whose top/bottom are given
// relative to the scroll frame's VISIBLE top (#2582). The toolbar renders ABOVE
// the line so it never occludes the prose (#1275), flipping below when there's
// no room. An anchor scrolled out of the visible box — the start of a selection
// longer than the viewport — pins the toolbar to the nearest visible edge, so a
// running prompt is always in view. The returned `y` is content-space (the
// toolbar is absolute in the scroll content).
export function placeAiToolbar(
  line: { top: number; bottom: number },
  frame: { height: number; scrollTop: number },
): { y: number; placement: "above" | "below" } {
  if (line.top > frame.height) return { y: frame.scrollTop + frame.height, placement: "above" };
  if (line.top < TOOLBAR_CLEARANCE) return { y: frame.scrollTop + Math.max(line.bottom, 0), placement: "below" };
  return { y: frame.scrollTop + line.top, placement: "above" };
}

export type AiSuggestionMeta = {
  provider: string;
  model: string;
  latency_ms: number;
  truncated: boolean;
  wordCount: number;
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};
