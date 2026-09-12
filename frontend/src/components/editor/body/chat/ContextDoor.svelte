<!--
  The Context door's interior (ADR-0076 S7): a read-only DRILL — root → a
  section (system / a lore tier / a conversation turn / inputs / journal) →,
  for a lore tier, an entry → that entry's own rendered XML element. Explicit
  panel-stack state (the ADR-0074 grammar), not `<details>`, so every level is
  a real, testable transition — and a lore tier's "N entries" now answers
  "which N" down to the exact context the model receives, not just a whole-tier
  blob.

  Extracted out of ChatComposerBar, which still owns the popover's positioned
  container + outside-click dismissal; this component owns the interior (head:
  back-arrow + panel title + close; body: the current panel's content). It
  shares the drill grammar's back-arrow affordance with NodePickerPopover
  (same glyph, same `.ctx-back` idiom) so the door and the picker read as one
  language — but this is NOT a picker: no tri-state, no selection, no writes.
-->
<script lang="ts">
  import { formatTokens } from "@/lib/utils/money";
  import {
    DECLARED_OVER_HINT,
    LEFT_OUT_HINT,
    declaredOverBudget,
    declaredOverLine,
    loreFitSummary,
    loreSourceLabel,
  } from "@/lib/chat/loreFit";
  import { isPromotedEntry, journalEntityCount, journalEntryKey } from "@/lib/chat/journal";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import type {
    ChangedPick,
    ChatSessionJournalEntry,
    LoreFit,
    PreviewCacheBlock,
    PreviewMessage,
  } from "@/lib/types";

  interface Props {
    previewCacheBlocks: PreviewCacheBlock[];
    // ADR-0086 S2: the lore-budget report the "Left out" section reads — the
    // LAST SENT turn's (`ChatSessionMessage.lore_fit`), or, before the first
    // send, the turn-0 preview's own fit. Null when no implicit selection ran.
    loreFit?: LoreFit | null;
    // The preview's left-out entries, each rendered (keyed by id) — only the
    // turn-0 fit has these on the wire; a sent turn's are fetched on request.
    loreLeftOutXml?: Record<string, string>;
    // Renders one left-out entry as-of the chat's scene, on request (the
    // chat-scoped lore-xml route). Resolves null for an entry that rendered
    // nothing; rejects when the render couldn't be done (the door says so and
    // re-asks on the next drill).
    fetchLeftOutXml?: (entryId: string) => Promise<string | null>;
    // The bound prompt id (or ""). Drives the System panel's pre-send guidance:
    // a prompt is bound but nothing has rendered yet → "fill the inputs".
    chatPromptEntryId: string;
    // Post-send: the locked system message. Pre-send: the assembled preview —
    // same fallback chain the System panel has always used.
    chatSystemPrompt: string;
    chatPreviewMessages: PreviewMessage[] | null;
    loreEnabled: boolean;
    lockedInputDisplays: { name: string; label: string; value: string }[];
    journal: ChatSessionJournalEntry[];
    // #1635: picked lore edited since the AI last saw it — listed in the
    // auto-added panel with an "· edited" marker.
    changedPicks: ChangedPick[];
    // id → title, for a tier's member entries and the locked-inputs display.
    titleFor: (id: string) => string | null;
    onClose: () => void;
  }

  let {
    previewCacheBlocks,
    loreFit = null,
    loreLeftOutXml = {},
    fetchLeftOutXml = async () => null,
    chatPromptEntryId,
    chatSystemPrompt,
    chatPreviewMessages,
    loreEnabled,
    lockedInputDisplays,
    journal,
    changedPicks,
    titleFor,
    onClose,
  }: Props = $props();

  // The partition moved verbatim from ChatComposerBar (ADR-0076 S2): cache
  // blocks that carry text, split into the system block, the lore tiers (each
  // now a drillable section), and everything else (conversation turns).
  const previewBlocksWithText = $derived(
    (previewCacheBlocks ?? []).filter((b) => b.text && b.text.trim()),
  );
  const systemBlock = $derived(previewBlocksWithText.find((b) => b.label === "system"));
  const tierBlocks = $derived(previewBlocksWithText.filter((b) => b.tier && b.label !== "system"));
  const otherBlocks = $derived(previewBlocksWithText.filter((b) => !b.tier));

  // The drill state: an explicit panel stack, not `<details>` — every level
  // (root, a section, a tier's entry) is a real pushed/popped state, so the
  // drill is fully testable and mirrors the picker's own grammar (ADR-0074).
  type Panel =
    | { kind: "root" }
    | { kind: "section"; key: string } // "system" | "tier:<label>" | "turn:<i>" | "inputs" | "journal" | "leftout"
    | { kind: "entry"; tierLabel: string; entryId: string }
    | { kind: "leftout-entry"; entryId: string };
  let stack = $state<Panel[]>([{ kind: "root" }]);
  const current = $derived(stack[stack.length - 1]);
  function drill(panel: Panel) {
    stack = [...stack, panel];
  }
  function back() {
    stack = stack.slice(0, -1);
  }

  // ADR-0086 §5: the "Left out" section exists when the last fit left
  // something out, or when the declared set alone exceeded a non-zero budget
  // (a budget of 0 is "declared only" — never "over"; `declaredOverBudget`).
  const leftOut = $derived(loreFit?.left_out ?? []);
  const declaredOver = $derived(loreFit != null && declaredOverBudget(loreFit));
  const showLeftOut = $derived(leftOut.length > 0 || declaredOver);
  const leftOutTokens = $derived(leftOut.reduce((sum, e) => sum + e.tokens, 0));
  // One title rule for the row and the panel head: the roster's live title,
  // else the report's snapshot, else the id (`||`, so an empty title falls through).
  function leftOutTitle(entryId: string): string {
    return titleFor(entryId) || leftOut.find((e) => e.id === entryId)?.title || entryId;
  }

  // A sent turn's left-out entries carry no XML on the wire; each is rendered
  // on request the first time it is drilled, as one cached promise the leaf
  // awaits. A rejected render stays in the cache so the leaf can say
  // "couldn't render" (never "rendered no XML"), and is marked so the next
  // drill of that entry asks again.
  let xmlRequests = $state<Record<string, Promise<string | null>>>({});
  let xmlFailed = $state<Record<string, boolean>>({});
  function drillLeftOut(entryId: string) {
    if (loreLeftOutXml[entryId] === undefined && (!xmlRequests[entryId] || xmlFailed[entryId])) {
      const request = fetchLeftOutXml(entryId);
      xmlFailed = { ...xmlFailed, [entryId]: false };
      request.catch(() => {
        xmlFailed = { ...xmlFailed, [entryId]: true };
      });
      xmlRequests = { ...xmlRequests, [entryId]: request };
    }
    drill({ kind: "leftout-entry", entryId });
  }

  function panelTitle(panel: Panel): string {
    if (panel.kind === "root") return "Context";
    if (panel.kind === "entry") return titleFor(panel.entryId) ?? panel.entryId;
    if (panel.kind === "leftout-entry") return leftOutTitle(panel.entryId);
    if (panel.key === "leftout") return "Left out";
    if (panel.key === "system") return "System";
    if (panel.key.startsWith("tier:")) return panel.key.slice("tier:".length);
    if (panel.key.startsWith("turn:")) {
      const i = Number(panel.key.slice("turn:".length));
      return otherBlocks[i]?.label ?? "";
    }
    if (panel.key === "inputs") return "Inputs (locked)";
    if (panel.key === "journal") return "Auto-added this conversation";
    return "";
  }
</script>

<header class="ctx-head">
  {#if stack.length > 1}
    <button type="button" class="ctx-back" aria-label="Back" onclick={back}>←</button>
  {/if}
  <span class="ctx-title">{panelTitle(current)}</span>
  <button type="button" class="ctx-close" aria-label="Close" onclick={onClose}>×</button>
</header>

<div class="ctx-body">
  {#if current.kind === "root"}
    <!-- Root: a menu of section rows, in fixed order, each shown only when it
         has content — the tier rows are what used to be whole-tier <details>. -->
    {#if systemBlock || (chatSystemPrompt && chatSystemPrompt.trim()) || (chatPreviewMessages && chatPreviewMessages.length > 0) || chatPromptEntryId}
      <button type="button" class="ctx-row" onclick={() => drill({ kind: "section", key: "system" })}>
        <span class="ctx-row-label">System</span>
        {#if loreEnabled}<span class="ctx-row-sub">lore-enabled</span>{/if}
        <GroupCaret size="xs" collapsed />
      </button>
    {/if}
    {#each tierBlocks as block (block.label)}
      <button
        type="button"
        class="ctx-row"
        onclick={() => drill({ kind: "section", key: "tier:" + block.label })}
      >
        <span class="ctx-row-label">{block.label}</span>
        <span class="ctx-row-sub">
          {block.entry_ids?.length ?? 0}
          {(block.entry_ids?.length ?? 0) === 1 ? "entry" : "entries"} ·
          {formatTokens(block.tokens)} tok
        </span>
        <GroupCaret size="xs" collapsed />
      </button>
    {/each}
    {#each otherBlocks as block, i (block.label + i)}
      <button type="button" class="ctx-row" onclick={() => drill({ kind: "section", key: "turn:" + i })}>
        <span class="ctx-row-label">{block.label}</span>
        <span class="ctx-row-sub">{formatTokens(block.tokens)} tok</span>
        <GroupCaret size="xs" collapsed />
      </button>
    {/each}
    {#if lockedInputDisplays.length > 0}
      <button type="button" class="ctx-row" onclick={() => drill({ kind: "section", key: "inputs" })}>
        <span class="ctx-row-label">Inputs (locked)</span>
        <span class="ctx-row-sub">{lockedInputDisplays.length} values</span>
        <GroupCaret size="xs" collapsed />
      </button>
    {/if}
    {#if journal.length > 0 || changedPicks.length > 0}
      <button type="button" class="ctx-row" onclick={() => drill({ kind: "section", key: "journal" })}>
        <span class="ctx-row-label">Auto-added this conversation</span>
        <span class="ctx-row-sub">{journalEntityCount(journal) + changedPicks.length}</span>
        <GroupCaret size="xs" collapsed />
      </button>
    {/if}
    {#if showLeftOut}
      <!-- ADR-0086 §5: what the lore budget left out of the last send (or,
           before the first send, of the turn-0 preview). A routine fact about
           the send in the door's ordinary register, not a warning. -->
      <button type="button" class="ctx-row" onclick={() => drill({ kind: "section", key: "leftout" })}>
        <span class="ctx-row-label">Left out</span>
        <span class="ctx-row-sub">
          {#if leftOut.length > 0}
            {leftOut.length} {leftOut.length === 1 ? "entry" : "entries"} · {formatTokens(leftOutTokens)} tok
          {:else}
            declared over budget
          {/if}
        </span>
        <GroupCaret size="xs" collapsed />
      </button>
    {/if}
    <p class="cbv-meta ctx-hint">
      This is the system message and context the assistant receives on the next turn.
      Chat history above is also sent. Composer text becomes the next user message —
      anything it newly mentions is auto-detected and joins the context at send.
    </p>
  {:else if current.kind === "section" && current.key === "system"}
    {#if loreEnabled}
      <div
        class="cbv-ctx-kv-line"
        title="The template invoked use_lore()/use() — the send path selects and attaches lore; the tiers below are where it lands."
      ><strong>lore-enabled</strong> · by this prompt</div>
    {/if}
    {#if systemBlock}
      <pre class="ctx-pre">{systemBlock.text}</pre>
    {:else if chatSystemPrompt && chatSystemPrompt.trim()}
      <pre class="ctx-pre">{chatSystemPrompt}</pre>
    {:else if chatPreviewMessages && chatPreviewMessages.length > 0}
      {#each chatPreviewMessages as message}
        <div class="cbv-preview-message">
          <header class="cbv-preview-msg-role">{message.role}</header>
          {#each message.blocks as block}
            <pre class="ctx-pre">{block.text}</pre>
          {/each}
        </div>
      {/each}
    {:else if chatPromptEntryId}
      <p class="cbv-meta">Fill the required inputs above and the assembled message will appear here.</p>
    {:else}
      <p class="cbv-meta">No system message will be sent. The model sees only the chat history.</p>
    {/if}
  {:else if current.kind === "section" && current.key.startsWith("tier:")}
    {@const tierLabel = current.key.slice("tier:".length)}
    {@const block = tierBlocks.find((b) => b.label === tierLabel)}
    {#if block}
      {#if block.entry_ids && block.entry_ids.length > 0}
        {#each block.entry_ids as id (id)}
          <button
            type="button"
            class="ctx-row"
            onclick={() => drill({ kind: "entry", tierLabel, entryId: id })}
          >
            <span class="ctx-row-label">{titleFor(id) ?? id}</span>
            <GroupCaret size="xs" collapsed />
          </button>
        {/each}
      {:else}
        <pre class="ctx-pre">{block.text}</pre>
      {/if}
    {/if}
  {:else if current.kind === "section" && current.key.startsWith("turn:")}
    {@const i = Number(current.key.slice("turn:".length))}
    {@const block = otherBlocks[i]}
    {#if block}
      <div class="cbv-preview-message">
        <header class="cbv-preview-msg-role">{block.label}</header>
        <pre class="ctx-pre">{block.text}</pre>
      </div>
    {/if}
  {:else if current.kind === "section" && current.key === "inputs"}
    <!-- Keyed by input NAME — labels are author-authored and can collide, and
         a duplicate key is a hard Svelte error. -->
    {#each lockedInputDisplays as pair (pair.name)}
      <div class="cbv-ctx-kv-line"><strong>{pair.label}</strong> · <span class="cbv-ctx-value">{pair.value}</span></div>
    {/each}
  {:else if current.kind === "section" && current.key === "journal"}
    <!-- Keyed by (id, source): an entry re-noticed from a better-ranked
         source is a second line, marked as the promotion it is (ADR-0086
         Amendment 1). The line says by which route, except the plain case
         of the author's own first mention. -->
    {#each journal as entry, i (journalEntryKey(entry))}
      <div class="cbv-ctx-kv-line">
        {entry.title || entry.entry_id}{#if entry.added_at_turn != null} · turn {entry.added_at_turn}{/if}{#if entry.source && entry.source !== "user_message"} · {loreSourceLabel(entry.source)}{:else if isPromotedEntry(journal, i)} · named{/if}
      </div>
    {/each}
    {#each changedPicks as pick (pick.id)}
      <div class="cbv-ctx-kv-line">
        {pick.title || pick.id} · <span class="ctx-edited">edited</span>
      </div>
    {/each}
  {:else if current.kind === "section" && current.key === "leftout" && loreFit}
    <!-- The fit's own figures first, then each left-out entry by fit order
         (the report's order), drillable to its element like a tier's entry. -->
    <div class="cbv-ctx-kv-line">
      <strong>{loreFitSummary(loreFit)}</strong> · {loreFit.kept} sent
    </div>
    {#if declaredOver}
      <div class="cbv-ctx-kv-line" title={DECLARED_OVER_HINT}>{declaredOverLine(loreFit)}</div>
    {/if}
    {#each leftOut as entry (entry.id)}
      <button type="button" class="ctx-row" onclick={() => drillLeftOut(entry.id)}>
        <span class="ctx-row-label">{leftOutTitle(entry.id)}</span>
        <span class="ctx-row-sub">{loreSourceLabel(entry.source)} · {formatTokens(entry.tokens)} tok</span>
        <GroupCaret size="xs" collapsed />
      </button>
    {/each}
    <p class="cbv-meta ctx-hint">{LEFT_OUT_HINT}</p>
  {:else if current.kind === "entry"}
    {@const block = tierBlocks.find((b) => b.label === current.tierLabel)}
    {@const xml = block?.entry_xml?.[current.entryId]}
    {#if xml}
      <pre class="ctx-pre">{xml}</pre>
    {:else}
      <p class="cbv-meta">This entry rendered no XML.</p>
    {/if}
  {:else if current.kind === "leftout-entry"}
    {@const known = loreLeftOutXml[current.entryId]}
    {#if known !== undefined}
      {#if known}<pre class="ctx-pre">{known}</pre>{:else}<p class="cbv-meta">This entry rendered no XML.</p>{/if}
    {:else}
      {#await xmlRequests[current.entryId]}
        <p class="cbv-meta">Rendering…</p>
      {:then xml}
        {#if xml}<pre class="ctx-pre">{xml}</pre>{:else}<p class="cbv-meta">This entry rendered no XML.</p>{/if}
      {:catch}
        <p class="cbv-meta">Couldn't render this entry right now. Go back and open it again to retry.</p>
      {/await}
    {/if}
  {/if}
</div>

<style>
  /* Head: back-arrow (drilled only) + panel title + close — the §4 popover
     head contract, bottom-bordered against the scrolling body below. */
  .ctx-head {
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: 9px 13px;
    border-bottom: 1px solid var(--divider);
    background: var(--panel);
    flex: none;
  }
  .ctx-title {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ctx-close {
    flex: none;
    background: transparent;
    border: none;
    cursor: pointer;
    font-size: var(--fs-lg);
    line-height: 1;
    padding: 0 2px;
    color: var(--text-3);
  }
  .ctx-close:hover {
    color: var(--text);
  }
  /* Mirrors NodePickerPopover's `.ctx-back` — the same glyph + class idiom so
     the door and the node picker read as one drill language. */
  .ctx-back {
    flex: none;
    width: 26px;
    height: 26px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: var(--accent);
    border-radius: var(--r-md);
    cursor: pointer;
    font-size: var(--fs-lg);
  }
  .ctx-back:hover {
    background: var(--inset);
  }

  .ctx-body {
    padding: 12px 14px;
    overflow-y: auto;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  /* A drillable row: label left, subtitle + trailing caret right. */
  .ctx-row {
    width: 100%;
    display: flex;
    align-items: center;
    gap: var(--sp-2);
    padding: var(--sp-2);
    border: none;
    border-radius: var(--r-md);
    background: transparent;
    cursor: pointer;
    text-align: left;
    color: var(--text);
    font: inherit;
  }
  .ctx-row:hover {
    background: var(--inset);
  }
  .ctx-row-label {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-md);
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .ctx-row-sub {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }

  /* The leaf content: rendered text (system fallback chain, a turn, or an
     entry's own XML element). */
  .ctx-pre {
    margin: 0 0 8px;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    line-height: 1.5;
    white-space: pre-wrap;
    word-wrap: break-word;
    color: var(--text);
  }
  .cbv-preview-message {
    margin-bottom: 10px;
  }
  .cbv-preview-msg-role {
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-3);
    margin-bottom: 3px;
  }
  .cbv-meta {
    margin: 0;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  .ctx-hint {
    font-style: italic;
    margin-top: var(--sp-2);
  }
  .cbv-ctx-kv-line {
    display: flex;
    gap: var(--sp-1);
    flex-wrap: wrap;
    font-size: var(--fs-sm);
    color: var(--text-2);
    margin-top: var(--sp-1);
  }
  .cbv-ctx-kv-line strong {
    font-weight: 600;
    color: var(--text);
  }
  .cbv-ctx-value {
    color: var(--text-2);
  }
  /* #1635: a picked lore entry edited since the AI last saw it. Informational,
     not a warning — the neutral accent axis, never amber (--warn), which on the
     quiet writing desk reads as "something is wrong" when nothing is. */
  .ctx-edited {
    color: var(--accent);
    font-weight: 600;
  }
</style>
