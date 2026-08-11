// AI provider / model / preview / generate / chat / invocation / chat-session
// wire types (#763.5). Extracted from types.ts to keep that barrel under the
// file-size cap; re-exported from `@/lib/types` so it stays the single import
// surface. A leaf module: nothing here references a non-AI type, and only
// `AIPolicy` is used back in types.ts (ProjectInfo, PromptEntryTypeExtras),
// which imports it from here.

export type AIPolicy = "off" | "local-only" | "cloud-allowed";

export type AIHealthResponse = {
  provider: string;
  model: string;
  ok: boolean;
  latency_ms: number;
  policy: AIPolicy;
  error?: string | null;
};

export type AIProviderInfo = {
  name: string;
  display_name: string;
};

export type AIProviderList = {
  providers: AIProviderInfo[];
};

export type AICapabilityTier = "fast" | "balanced" | "premium" | "reasoning" | "local";

export type AIModelInfo = {
  id: string;
  display_name: string;
  provider: string;
  context_window: number;
  tier: AICapabilityTier;
  capabilities: string[];
  deprecated: boolean;
  sunset_date?: string | null;
  successor?: string | null;
  cost_in_per_mtok?: number | null;
  cost_out_per_mtok?: number | null;
  cache_read_multiplier?: number | null;
};

export type AIProviderModelList = {
  provider: string;
  models: AIModelInfo[];
};

export type AITierResolution = {
  provider: string;
  tier: string;
  model_id: string | null;
};

export type AIPreviewRequest = {
  template_source: string;
  target_scene_id: string;
  session_id?: string | null;
  inputs?: Record<string, unknown>;
  text_before?: string;
  text_after?: string;
  commit?: boolean;
  // Explicit mutation resolution scene from a `scene_ref` input (ADR-0012);
  // overrides target_scene_id for effective-state resolution.
  resolution_scene_id?: string;
  // ADR-0051 S5: the bound chat's subject. A scene subject is the chat's
  // anchored scene (the old target_scene_id) — the backend derives the scene
  // from it as the lowest-priority `{{ scene }}` binding, so a resumed chat
  // renders its scene without the frontend knowing which subjects are scenes.
  subject?: string;
  // V2: when set, preview response includes estimated_cost_usd + caching_style.
  assistant_id?: string | null;
};

export type PreviewContentBlock = {
  text: string;
  cache_break_after: boolean;
};

export type PreviewMessage = {
  role: string;
  blocks: PreviewContentBlock[];
};

export type PreviewCacheBlock = {
  label: string;
  role: string;
  tokens: number;
  cache_break_after: boolean;
};

// Populated on AIPreviewResponse.error when the render failed. The preview
// endpoint returns 200 with this set rather than throwing — the editor
// auto-fires preview before required inputs are filled, so an unrendered
// template is an expected state. `/api/ai/generate` still throws.
export type PreviewErrorInfo = {
  message: string;
  // "undefined" — Jinja UndefinedError; undefined_name set when derivable.
  // "syntax"    — TemplateSyntaxError; line set.
  // "scene_not_found" — preview target_scene_id didn't resolve.
  // "other"     — catch-all.
  kind: "undefined" | "syntax" | "scene_not_found" | "other";
  line?: number | null;
  col?: number | null;
  undefined_name?: string | null;
};

export type AIPreviewResponse = {
  messages: PreviewMessage[];
  warnings: string[];
  char_count: number;
  session_id?: string | null;
  rendered: boolean;
  error?: PreviewErrorInfo | null;
  // V2 telemetry. estimated_tokens always populated; cost null when no
  // assistant or pricing unknown.
  estimated_tokens?: number;
  cache_blocks?: PreviewCacheBlock[];
  estimated_cost_usd?: number | null;
  provider?: string | null;
  model?: string | null;
  caching_style?: "none" | "auto" | "explicit" | null;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  // UI-side accumulator fields populated during the streaming chat turn.
  // Optional on the wire — the backend ignores extras on send.
  thinking?: string;
  truncated?: boolean;
  journal_added?: ChatSessionJournalEntry[];
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type AIChatRequest = {
  provider?: string | null;
  model?: string | null;
  assistant_id?: string | null;
  system_prompt?: string;
  messages: ChatMessage[];
  max_tokens?: number;
  chat_id?: string | null;
};

export type ChatUsage = {
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  output_tokens: number;
};

export type AIChatResponse = {
  role: "assistant";
  content: string;
  provider: string;
  model: string;
  latency_ms: number;
  policy: AIPolicy;
  ok: boolean;
  error?: string | null;
  stop_reason?: string | null;
  truncated: boolean;
  journal_added?: ChatSessionJournalEntry[];
  // V2 telemetry. Null on failure or when provider didn't return usage.
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type AIGenerateRequest = {
  template_source: string;
  target_scene_id: string;
  session_id?: string | null;
  inputs?: Record<string, unknown>;
  text_before?: string;
  text_after?: string;
  selection?: string;
  commit?: boolean;
  // Explicit mutation resolution scene from a `scene_ref` input (ADR-0012);
  // overrides target_scene_id for effective-state resolution.
  resolution_scene_id?: string;
  provider?: string | null;
  model?: string | null;
  assistant_id?: string | null;
  max_tokens?: number;
};

export type AIContextPresetResponse = {
  kind: string;
  content: string;
};

export type AIGenerateResponse = {
  content: string;
  rendered_messages: PreviewMessage[];
  rendered_warnings: string[];
  char_count: number;
  provider: string;
  model: string;
  latency_ms: number;
  policy: AIPolicy;
  ok: boolean;
  error?: string | null;
  stop_reason?: string | null;
  truncated: boolean;
  session_id?: string | null;
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type AIInvocation = {
  id: string;
  ts: string;
  prompt_entry_id?: string;
  prompt_entry_type?: string;
  scene_id?: string;
  character_id?: string;
  provider?: string;
  model?: string;
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type AIInvocationList = {
  invocations: AIInvocation[];
};

export type CreateAIInvocationRequest = {
  prompt_entry_id?: string;
  prompt_entry_type?: string;
  scene_id?: string;
  character_id?: string;
  provider?: string;
  model?: string;
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type ChatSessionMessage = {
  role: "user" | "assistant";
  content: string;
  thinking?: string;
  truncated?: boolean;
  journal_added?: ChatSessionJournalEntry[];
  usage?: ChatUsage | null;
  cost_usd?: number | null;
};

export type ChatSessionContextItem = {
  kind: "scene" | "lore" | "snippet" | "preset";
  id: string;
  entry_type?: string;
  title?: string;
};

export type ChatSessionJournalEntry = {
  entry_id: string;
  title?: string;
  entry_type?: string;
  added_at_turn?: number;
  source?: "user_message" | "rendered_prompt" | "depth1_expansion";
};

export type ChatSession = {
  id: string;
  title: string;
  prompt_entry_id: string;
  assistant_id: string;
  system_prompt: string;
  // ADR-0051 S2/S5: the node this chat is about (a lore entry / character /
  // scene). Surfaces "chats about X" via the reverse-reference index. **A scene
  // subject IS the chat's anchored scene** (S5 folded the old target_scene_id):
  // the backend derives the render/journal scene from it. Empty for freeform.
  subject?: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  context_items: ChatSessionContextItem[];
  messages: ChatSessionMessage[];
  inputs?: Record<string, unknown>;
  journal?: ChatSessionJournalEntry[];
  // V2: running USD cost (display as EUR via money.ts).
  cost_usd_total?: number;
  // V2: per-cache-slot ISO timestamps of last cache write.
  cache_write_times?: Record<string, string>;
};

export type ChatSessionSummary = {
  id: string;
  title: string;
  prompt_entry_id: string;
  assistant_id: string;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  message_count: number;
  cost_usd_total?: number;
};

export type ChatSessionList = {
  sessions: ChatSessionSummary[];
};

export type CreateChatSessionRequest = {
  title?: string;
  prompt_entry_id?: string;
  assistant_id?: string;
  system_prompt?: string;
  // ADR-0051 S2/S5: the node this chat is about (a lore entry / scene). Persisted
  // into the chat's metadata.subject so the index extracts a chat→subject edge.
  // A scene subject is also the chat's anchored scene (folded target_scene_id).
  subject?: string;
};

export type SaveChatSessionRequest = {
  title: string;
  prompt_entry_id: string;
  assistant_id: string;
  system_prompt: string;
  // ADR-0051 S2/S5: echoed on save so the subject survives per-turn writes;
  // backend falls back to the persisted value when omitted. Carries the scene
  // anchor for scene chats (folded target_scene_id).
  subject?: string;
  pinned: boolean;
  context_items: ChatSessionContextItem[];
  messages: ChatSessionMessage[];
  inputs?: Record<string, unknown>;
  journal?: ChatSessionJournalEntry[];
  // V2: incremental cost to ADD to persisted cost_usd_total. Backend
  // clamps negatives to 0 (cost is monotonic).
  cost_delta_usd?: number;
  // V2: slot labels whose cache_write_times entry should be stamped
  // with the current server time. Send when the response's usage had
  // cache_write_tokens > 0 for that slot.
  cache_write_slots?: string[];
};
