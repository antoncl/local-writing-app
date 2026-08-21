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

export type AiSuggestionMeta = {
  provider: string;
  model: string;
  latency_ms: number;
  truncated: boolean;
  wordCount: number;
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};
