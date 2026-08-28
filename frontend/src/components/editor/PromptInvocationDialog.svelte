<!--
  PromptInvocationDialog — the "fill the declared inputs, then fire" modal for a
  prompt entry (roleplay, revise, etc.). A self-contained subsystem lifted out
  of the NodeEditor shell (#631): it owns the dialog's draft/assistant/error
  state, the live token+cost estimate (debounced-by-token async preview), and
  the InputsDialog render branch.

  Opened imperatively by the host (`bind:this` → `open(...)`), which routes
  ProseBodyView's `request-inputs-dialog` here. On submit it hands the resolved
  inputs back through `onRun` — the host owns the AI streaming machinery
  (ProseBodyView.runPromptEntryWithInputsExternal), so this component never
  reaches into the body view.
-->
<script lang="ts">
  import InputsDialog from "@/components/editor/InputsDialog.svelte";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import {
    effectivePromptInputs,
    promptEntryDescription,
    resolutionSceneIdFromInputs,
    type PromptResolutionContext,
  } from "@/lib/editor-core/promptResolution";
  import { coerceInputValue, isInputMissing } from "@/lib/utils/promptInputs";
  import { api } from "@/lib/api";
  import type {
    AssistantEntrySummary,
    EditableDocument,
    LoreEntrySummary,
    PromptEntrySummary,
    PromptInputDefinition,
    StructureDocument,
  } from "@/lib/types";

  interface Props {
    scene?: EditableDocument | null;
    assistantEntries?: AssistantEntrySummary[];
    defaultAssistantId?: string;
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    // The host owns the AI streaming machinery; submit forwards the resolved
    // inputs here (ProseBodyView.runPromptEntryWithInputsExternal).
    onRun?: ((entry: PromptEntrySummary, inputs: Record<string, unknown>, assistantId: string) => Promise<void>) | undefined;
  }

  let {
    scene = null,
    assistantEntries = [],
    defaultAssistantId = "",
    structure = null,
    researchStructure = null,
    loreEntries = [],
    promptEntries = [],
    implicitContextMatcher = null,
    onRun = undefined,
  }: Props = $props();

  const metadataSchema = $derived($metadataSchemaStore);
  // Minimal context for promptEntryDescription (reads metadataSchema only).
  const descCtx = $derived<PromptResolutionContext>({
    metadataSchema,
    promptEntries,
    loreEntries,
    availableScenes: [],
  });

  let entry: PromptEntrySummary | null = $state(null);
  // Inline error inside the dialog — populated when a positional arg (e.g. from
  // `/roleplay Irene`) failed to resolve, so the user can see WHY the dialog
  // opened instead of firing directly.
  let error: string | null = $state(null);
  let drafts: Record<string, string> = $state({});
  // "" means: use the user's default assistant (resolved server-side).
  let assistantId: string = $state("");
  // Tracked so the "previously used" path can pre-fill drafts.
  let lastInvokedEntryId: string | null = null;
  let lastInvokedInputs: Record<string, unknown> = {};
  // V2: token + cost estimate for the about-to-fire continuation. Recomputed
  // when the dialog's prompt / drafts / assistant change. Null when closed.
  let estimate: {
    tokens: number;
    cost_usd: number | null;
    caching_style: "none" | "auto" | "explicit" | null;
    cache_blocks: { label: string; tokens: number; tier?: string | null }[];
  } | null = $state(null);
  // Monotonic token guarding async preview races — bumps on every fetch; late
  // responses with a stale token drop their result.
  let estimateToken = 0;

  // Opened by the host. Seeds drafts from the "previously used" inputs (same
  // entry) or the declared defaults, then applies any positional prefill and
  // the unresolved-token error that made ProseBodyView open the dialog.
  export function open(payload: {
    entry: PromptEntrySummary;
    prefilledDrafts?: Record<string, string>;
    unresolved?: Array<{ name: string; label: string; token: string }>;
  }): void {
    const { entry: nextEntry, prefilledDrafts, unresolved } = payload;
    const declared = effectivePromptInputs(nextEntry);
    const prior = lastInvokedEntryId === nextEntry.id ? lastInvokedInputs : {};
    const seeded: Record<string, string> = {};
    for (const input of declared) {
      const previous = prior[input.name];
      if (previous !== undefined && previous !== null) {
        seeded[input.name] = String(previous);
      } else if (input.default !== undefined && input.default !== null) {
        seeded[input.name] = String(input.default);
      } else {
        // Seed everything to "" — the runtime's unset state, consistent with
        // the preview (#42). The runtime is tri-state (Unset/True/False) so the
        // user explicitly picks True or False or leaves it unset.
        seeded[input.name] = "";
      }
    }
    if (prefilledDrafts) {
      for (const [name, value] of Object.entries(prefilledDrafts)) {
        seeded[name] = value;
      }
    }
    drafts = seeded;
    // Seed with the user's default; the picker shows it as "Default (Name)".
    assistantId = "";
    error =
      unresolved && unresolved.length > 0
        ? unresolved.map((u) => `Couldn't find "${u.token}" for ${u.label}`).join(" · ")
        : null;
    entry = nextEntry;
  }

  function cancel() {
    entry = null;
    drafts = {};
    assistantId = "";
    error = null;
  }

  function updateDraft(name: string, value: string) {
    drafts = { ...drafts, [name]: value };
  }

  function assistantDisplayName(id: string): string {
    if (!id) return "";
    return assistantEntries.find((a) => a.id === id)?.title ?? "";
  }

  async function fetchEstimate(): Promise<void> {
    const current = entry;
    if (!current) {
      estimate = null;
      return;
    }
    const ourToken = ++estimateToken;
    const declared = effectivePromptInputs(current);
    const inputs: Record<string, unknown> = {};
    for (const input of declared) {
      const raw = drafts[input.name] ?? "";
      const coerced = coerceInputValue(raw, input.type);
      if (coerced !== null && coerced !== "") inputs[input.name] = coerced;
    }
    try {
      const preview = await api.aiPreview({
        template_source: current.body,
        target_scene_id: scene?.id ?? "",
        inputs,
        resolution_scene_id: resolutionSceneIdFromInputs(current, inputs),
        commit: false,
        assistant_id: assistantId || null,
      });
      if (ourToken !== estimateToken) return;
      // Render errors come back as 200 + preview.error (the endpoint is
      // exploratory). Errors surface when the user runs, so keep the estimate
      // strip quiet — null out instead of flickering a stale value.
      if (preview.error) {
        estimate = null;
        return;
      }
      estimate = {
        tokens: preview.estimated_tokens ?? 0,
        cost_usd: preview.estimated_cost_usd ?? null,
        caching_style: preview.caching_style ?? null,
        cache_blocks: (preview.cache_blocks ?? []).map((b) => ({
          label: b.label,
          tokens: b.tokens,
          tier: b.tier,
        })),
      };
    } catch {
      // Non-render failure (project closed, 5xx, etc.) — same UX.
    }
  }

  async function submit() {
    const current = entry;
    if (!current) return;
    const declared = effectivePromptInputs(current);
    // The one shared emptiness predicate (#1482) — same rule the chat
    // inputs-strip gates Send on, so the two surfaces can't disagree.
    const missing = declared.filter(
      (input) => input.required && isInputMissing(input, drafts[input.name]),
    );
    if (missing.length > 0) {
      error = `Missing required: ${missing.map((i) => i.label || i.name).join(", ")}.`;
      return;
    }
    const values: Record<string, unknown> = {};
    for (const input of declared) {
      const raw = drafts[input.name] ?? "";
      const coerced = coerceInputValue(raw, input.type);
      if (coerced !== null && coerced !== "") values[input.name] = coerced;
    }
    const pickedAssistantId = assistantId;
    lastInvokedEntryId = current.id;
    lastInvokedInputs = values;
    entry = null;
    drafts = {};
    assistantId = "";
    await onRun?.(current, values, pickedAssistantId);
  }

  // Refetch when the dialog's prompt / drafts / assistant change. Per
  // [[feedback-svelte5-reactivity-traps]], read each dep on its own line so
  // Svelte tracks them — a function call alone wouldn't.
  $effect.pre(() => {
    void entry;
    void drafts;
    void assistantId;
    void fetchEstimate();
  });
</script>

{#if entry}
  <InputsDialog
    entry={entry}
    description={promptEntryDescription(descCtx, entry)}
    declaredInputs={effectivePromptInputs(entry)}
    drafts={drafts}
    assistantId={assistantId}
    defaultAssistantLabel={assistantDisplayName(defaultAssistantId) || "use machine default"}
    assistantEntries={assistantEntries}
    error={error}
    estimate={estimate}
    structure={structure}
    researchStructure={researchStructure}
    loreEntries={loreEntries}
    promptEntries={promptEntries}
    excludeId={scene?.id ?? null}
    implicitContextMatcher={implicitContextMatcher}
    onUpdateDraft={(detail) => updateDraft(detail.name, detail.value)}
    onUpdateAssistant={(detail) => (assistantId = detail.assistantId)}
    onCancel={cancel}
    onSubmit={() => void submit()}
  />
{/if}
