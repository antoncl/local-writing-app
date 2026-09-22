// The turn-0 cost estimate + preview (#2129, extracted from ChatBodyView's
// fetchChatEstimate — the source of truth for this shape), as a per-instance
// rune controller in the `ChatCommitController` shape (chatCommit.svelte.ts):
// `$state` fields the host reads/renders, wired once via a `deps` object of
// getters into the component's reactive state. ChatBodyView's `$effect.pre`
// still lists its own deps explicitly and calls `void estimate.fetch()` — the
// getters read component state synchronously inside that effect, so tracking
// is unchanged; nothing here is a `$derived` over component state.
import { api } from "@/lib/api";
import { resolutionSceneIdFromInputs } from "@/lib/editor-core/promptResolution";
import type { ChatEstimate, LoreFit, PreviewCacheBlock, PreviewMessage, PromptEntrySummary } from "@/lib/types";

export interface ChatEstimateDeps {
  /** The prompt entry bound to the chat, already resolved by the host
   *  (`promptEntries.find(p => p.id === chatPromptEntryId)`), or null when no
   *  prompt is bound / it isn't in the roster. */
  getPromptEntry: () => PromptEntrySummary | null;
  /** The coerced+expanded input set for the render (promptResolution.ts'
   *  inputValuesFromDrafts — Seam 0). */
  getInputs: () => Record<string, unknown>;
  /** The chat's bound subject ("" for freeform / Chats-pane chats). */
  getSubject: () => string;
  /** Assistant bound to the chat, or "" for the machine default. */
  getAssistantId: () => string;
  /** Whether this fetch may still write the lore gate (ADR-0076 S2): only
   *  pre-lock, not mid-send — today `!isLocked && !chatRunning &&
   *  !chatSystemPrompt`. Once the lock render has captured the authoritative
   *  value it owns the field. */
  mayCaptureLoreGate: () => boolean;
  /** Write the mirrored lore gate — component-owned (`chatLoreEnabled`). */
  setLoreEnabled: (v: boolean) => void;
}

export class ChatEstimateController {
  // Next-turn estimate. Recomputed whenever the inputs that drive it
  // change (prompt, assistant, drafts). Null when no prompt is bound —
  // a freeform brief renders no template so there's nothing to estimate
  // pre-send (the per-turn actuals on the assistant reply tell the user
  // what it cost retroactively).
  estimate = $state<ChatEstimate | null>(null);
  // The rendered messages from the last successful estimate fetch (system +
  // any templated initial turns). Null when no prompt is bound (freeform: no
  // system message) or the template hasn't rendered yet (unfilled inputs).
  previewMessages = $state<PreviewMessage[] | null>(null);
  // The send-path cache blocks (system + attached lore tiers) WITH text — what
  // the model actually receives. The preview popover renders these so the lore
  // is visible; it lives only in a cache block, never the rendered template.
  previewCacheBlocks = $state<PreviewCacheBlock[]>([]);
  // ADR-0086 S2: the turn-0 preview's own budget fit and its left-out entries'
  // rendered elements, one cell — what the door's "Left out" section reads
  // before the first send. Once a turn has reported, the last reporting turn's
  // `lore_fit` takes over (a stopped or streaming turn never receives one, so
  // it must not hide the last that did) and a left-out entry's XML is rendered
  // on request instead (chatLoreXml).
  previewLore = $state<{ fit: LoreFit | null; leftOutXml: Record<string, string> } | null>(null);

  // Stale-response guard: every fetch grabs ourToken = ++token; on resolve we
  // drop the response if the token moved. Out-of-order resolutions are common
  // when the user types fast.
  private token = 0;

  constructor(private readonly deps: ChatEstimateDeps) {}

  reset(): void {
    this.estimate = null;
    this.previewMessages = null;
    this.previewCacheBlocks = [];
    this.previewLore = null;
  }

  async fetch(): Promise<void> {
    // Invalidate any in-flight fetch FIRST — including on the early returns.
    // Bumping after them let a previous chat's response land after a switch to
    // a promptless chat (same token, isLocked false) and write that chat's
    // lore gate onto this one (S2 review).
    const ourToken = ++this.token;
    const entry = this.deps.getPromptEntry();
    if (!entry) {
      this.reset();
      return;
    }
    const inputs = this.deps.getInputs();
    try {
      const preview = await api.aiPreview({
        template_source: entry.body,
        // ADR-0051 S5: scene derives from the chat's subject (see first-send).
        target_scene_id: "",
        subject: this.deps.getSubject(),
        inputs,
        resolution_scene_id: resolutionSceneIdFromInputs(entry, inputs),
        commit: false,
        assistant_id: this.deps.getAssistantId() || null,
      });
      if (ourToken !== this.token) return;
      // Preview render errors come back as 200 + preview.error. Don't show
      // them in the estimate strip — they'll surface when the user sends.
      if (preview.error) {
        this.reset();
        return;
      }
      this.previewMessages = preview.messages ?? null;
      // Keep the block TEXT (the estimate strip strips it to label/tokens); the
      // preview popover needs it to show the attached lore.
      this.previewCacheBlocks = preview.cache_blocks ?? [];
      this.previewLore = { fit: preview.lore_fit ?? null, leftOutXml: preview.lore_left_out_xml ?? {} };
      // ADR-0076 S2: pre-lock, this fetch is the only place the lore gate is
      // known — mirror the lock render's capture (renderAndLockPromptTemplate)
      // so the Context door's "lore-enabled" annotation is live while the
      // writer is still filling inputs. Once the lock render has captured the
      // authoritative value it owns the field — guard on the SAME signals the
      // lock sets (system prompt) plus the in-flight send, not just isLocked:
      // during the first send's persist await the history is still empty, so a
      // stale estimate resolving in that window would clobber the lock's
      // capture and persist a wrong gate (S2 review).
      if (this.deps.mayCaptureLoreGate()) {
        this.deps.setLoreEnabled(preview.lore_enabled ?? false);
      }
      this.estimate = {
        tokens: preview.estimated_tokens ?? 0,
        cost_usd: preview.estimated_cost_usd ?? null,
        cached: preview.cached ?? null,
        warnings: preview.warnings ?? [],
        // The meta line now reads these summaries for the cache term
        // (ADR-0084 §6, `cacheTermSecondsFor`) — the door still reads the
        // FULL blocks via previewCacheBlocks above for text/entries.
        cache_blocks: (preview.cache_blocks ?? []).map((b) => ({
          label: b.label,
          tokens: b.tokens,
          tier: b.tier,
          cached: b.cached,
          ttl_seconds: b.ttl_seconds,
        })),
      };
    } catch {
      // Non-render failure — same UX.
    }
  }
}
