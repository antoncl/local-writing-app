import type {
  AIChatRequest,
  AIChatResponse,
  AIContextPresetResponse,
  AIGenerateRequest,
  AIHealthResponse,
  OllamaHostHealth,
  AIProviderList,
  AIProviderModelList,
  AITierResolution,
  AIPreviewRequest,
  AIPreviewResponse,
  AIInvocation,
  AIInvocationList,
  CreateAIInvocationRequest,
} from "@/lib/types";
import { request, streamNdjson } from "./core";

export const aiApi = {
  listAIProviders() {
    return request<AIProviderList>("/ai/providers");
  },
  listAIProviderModels(provider: string, forceRefresh = false) {
    const qs = forceRefresh ? "?force_refresh=true" : "";
    return request<AIProviderModelList>(`/ai/providers/${encodeURIComponent(provider)}/models${qs}`);
  },
  resolveAIProviderTier(provider: string, tier: string) {
    return request<AITierResolution>(
      `/ai/providers/${encodeURIComponent(provider)}/resolve-tier?tier=${encodeURIComponent(tier)}`,
    );
  },
  // `assistantId` targets a specific assistant so the check tests the one a
  // send will actually use — omit it and the backend resolves the topmost
  // assistant (the default smoke test in Machine Settings). #336.
  aiHealth(assistantId?: string, provider?: string, model?: string) {
    return request<AIHealthResponse>("/ai/health", {
      method: "POST",
      body: JSON.stringify({
        assistant_id: assistantId ?? null,
        provider: provider ?? null,
        model: model ?? null,
      }),
    });
  },
  // Model-less reachability probe of the Ollama host — "can this machine reach
  // the daemon / is the firewall open?" — tests the typed host so a user can
  // check before saving (#1380). Never throws for "offline"; that's `reachable:
  // false` with a hint.
  checkOllamaHost(host: string) {
    return request<OllamaHostHealth>("/ai/ollama/health", {
      method: "POST",
      body: JSON.stringify({ host }),
    });
  },
  aiPreview(payload: AIPreviewRequest) {
    return request<AIPreviewResponse>("/ai/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  aiChat(payload: AIChatRequest) {
    return request<AIChatResponse>("/ai/chat", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  aiChatStream(payload: AIChatRequest, signal?: AbortSignal) {
    return streamNdjson("/ai/chat/stream", payload, signal);
  },
  aiGenerateStream(payload: AIGenerateRequest, signal?: AbortSignal) {
    return streamNdjson("/ai/generate/stream", payload, signal);
  },
  aiContextPreset(kind: "full_outline" | "full_text") {
    return request<AIContextPresetResponse>(`/ai/context-preset?kind=${encodeURIComponent(kind)}`);
  },
  aiAppendInvocation(payload: CreateAIInvocationRequest) {
    return request<AIInvocation>("/ai/invocations", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  aiListInvocations(params: { scene_id?: string; character_id?: string } = {}) {
    const search = new URLSearchParams();
    if (params.scene_id) search.set("scene_id", params.scene_id);
    if (params.character_id) search.set("character_id", params.character_id);
    const query = search.toString();
    return request<AIInvocationList>(
      query ? `/ai/invocations?${query}` : "/ai/invocations",
    );
  },
};
