// Shared types for ProseBodyView's floating AI inline toolbar.
// The host (the AI-suggestion pipeline) owns the generation/suggestion state
// and where the toolbar shows (aiToolbarPosition); the presentational
// ProseAIToolbar component renders the status / accept-retry-discard controls
// and the usage-cost meta from these.

import type { ChatUsage } from "@/lib/types";

export type AiToolbarPosition = { x: number; y: number; visible: boolean };

export type AiSuggestionMeta = {
  provider: string;
  model: string;
  latency_ms: number;
  truncated: boolean;
  wordCount: number;
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};
