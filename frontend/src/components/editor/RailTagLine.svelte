<script lang="ts">
  // A tags field renders as ONE mono line, never pills (#2007): a tag-vocabulary
  // `entity_ref_list` (ADR-0082 — the picker reduces to the single kind `tag`)
  // is the RAIL's own read/edit widget, distinct from the generic ref-list pills
  // (`ReferencePicker`/`FieldValueEditor`). At rest the line is one hit button
  // (RailScalarCell's rest/edit flip contract — `editing`/`onOpen`/`onClose`);
  // editing appends a plain-text input with an inline completion list, so
  // picking or minting a tag never leaves the line for a popover.
  import { tick } from "svelte";
  import { tagById, liveTags, canonicalIdIn, resolveOrCreateTag } from "@/lib/stores/tagNodes";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { singleConcreteTarget, createTargetFor, hasTitleMatch } from "@/lib/utils/pickerCreate";
  import { peekAnchor } from "@/lib/actions/peekAnchor";
  import { buildPeekTarget } from "@/lib/utils/peekTarget";
  import { buildRefResolver } from "@/lib/utils/refResolve";
  import { referenceIndexStore } from "@/lib/stores/references";
  import PeekCard from "@/components/widgets/PeekCard.svelte";
  import type {
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataValue,
    NavigateTarget,
    PromptEntrySummary,
    StructureDocument,
    TagEntry,
  } from "@/lib/types";

  // The rosters the tag peek card's carrier breakdown needs to bucket a
  // non-tag carrier by its own kind (#2011 follow-up) — the subset of
  // RailFieldRow's `RailRowDeps` that `buildRefResolver` actually reads
  // (it has no `researchStructure` param — a research note is never a tag
  // carrier). Optional/defaulted: every existing call site keeps working
  // unchanged, just with an "Other"-only breakdown until it threads these too.
  interface Deps {
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
  }

  interface Props {
    field: MetadataFieldDefinition;
    fieldId: string;
    fieldLabel: string;
    value: MetadataValue;
    readOnly?: boolean;
    editing: boolean;
    onOpen: (fieldId: string, rowEl: HTMLElement) => void;
    onClose: (fieldId: string) => void;
    createLayerId?: string | null;
    onChange: (ids: string[]) => void;
    onNavigate?: (target: NavigateTarget) => void;
    deps?: Deps;
  }

  let {
    field,
    fieldId,
    fieldLabel,
    value,
    readOnly = false,
    editing,
    onOpen,
    onClose,
    createLayerId = undefined,
    onChange,
    onNavigate,
    deps = {},
  }: Props = $props();

  const schema = $derived($metadataSchemaStore);
  // The field's own vocabulary (a single concrete tag entry_type) — undefined
  // when the picker offers any tag vocabulary; the completion list then shows
  // each candidate's vocabulary so they stay distinguishable.
  const fieldVocab = $derived(singleConcreteTarget(field.picker_config, schema)?.entryType);
  const createTarget = $derived(createTargetFor(field.picker_config, schema));

  function vocabLabel(entryType: string): string {
    return schema?.entry_types?.[entryType]?.name ?? entryType;
  }

  const ids = $derived(Array.isArray(value) ? value.map((v) => String(v)) : []);
  type ResolvedTag = { id: string; title: string; entryType: string | null; missing: boolean };
  const items = $derived.by((): ResolvedTag[] => {
    const byId = $tagById;
    return ids.map((id) => {
      const canonical = canonicalIdIn(byId, id);
      const tag = byId.get(canonical);
      if (!tag) return { id, title: id, entryType: null, missing: true };
      return { id, title: tag.title, entryType: tag.entry_type, missing: false };
    });
  });
  const isEmpty = $derived(ids.length === 0);

  // Grouping (rest display only): one flat run when every resolved tag shares
  // a vocabulary, else a vocabulary-labelled group per distinct entry_type, in
  // first-appearance order. A missing id contributes no vocabulary — it never
  // forces a multi-group split on its own.
  type DisplayGroup = { key: string; label: string | null; items: ResolvedTag[] };
  const restGroups = $derived.by((): DisplayGroup[] => {
    const groups: DisplayGroup[] = [];
    const byKey = new Map<string, DisplayGroup>();
    for (const item of items) {
      const key = item.entryType ?? "~missing";
      let group = byKey.get(key);
      if (!group) {
        group = { key, label: item.entryType ? vocabLabel(item.entryType) : null, items: [] };
        byKey.set(key, group);
        groups.push(group);
      }
      group.items.push(item);
    }
    return groups;
  });
  const singleVocab = $derived(
    new Set(items.filter((i) => !i.missing).map((i) => i.entryType)).size <= 1,
  );

  // The plain text a screen reader hears for the rest hit's value — mirrors
  // the DOM render below (single flat run, or vocab-labelled groups joined
  // by " | "), just without the markup.
  const plainText = $derived(
    singleVocab
      ? items.map((i) => i.title).join(" · ")
      : restGroups
          .map((g) => (g.label ? `${g.label}: ` : "") + g.items.map((i) => i.title).join(" · "))
          .join(" | "),
  );
  const ariaLabel = $derived(isEmpty ? `Set ${fieldLabel}` : `Edit ${fieldLabel}: ${plainText}`);

  function navigate(id: string, entryType: string | null) {
    onNavigate?.({ id, kind: "tag", entryType: entryType ?? undefined });
  }

  // --- Peek card (#2011): the rest line is ONE `.fr-rest-hit` button, so a
  // per-name hover/focus preview needs peekAnchor's delegated mode — it
  // matches `.tag-line-name[data-tag-id]` inside the button and hands back
  // the hovered span itself as the anchor. Per-name keyboard focus isn't
  // reachable on this one-button line either way (the whole line is a single
  // tab stop); the edit mode's own completion list is the keyboard path for
  // these tags, so that is not a regression peek cards need to fix. -----
  let peek = $state<{ item: ResolvedTag; anchor: HTMLElement } | null>(null);
  function openPeek(anchor: HTMLElement) {
    const id = anchor.dataset.tagId;
    const item = id ? items.find((i) => i.id === id) : undefined;
    if (!item || item.missing) return;
    peek = { item, anchor };
  }
  function closePeek() {
    peek = null;
  }
  // The shared id → node walk (lib/utils/refResolve.ts) — same as
  // ReferencePicker/ReferenceListTab, so a scene/lore carrier in the tag's
  // breakdown resolves to its real kind instead of falling through to
  // "other"; `tagById` keeps the existing tag-title fallback for a carrier
  // that is itself another tag.
  const peekResolver = $derived(
    buildRefResolver({
      structure: deps.structure,
      loreEntries: deps.loreEntries,
      promptEntries: deps.promptEntries,
      tagById: $tagById,
    }),
  );
  const peekModel = $derived(
    peek
      ? buildPeekTarget(
          { id: peek.item.id, kind: "tag", title: peek.item.title, entry_type: peek.item.entryType ?? undefined },
          schema,
          {
            resolveRef: peekResolver,
            referenceIndex: $referenceIndexStore,
            canonicalTagId: (id) => canonicalIdIn($tagById, id),
          },
        )
      : null,
  );
  function peekRemove() {
    if (!peek) return;
    onChange(ids.filter((other) => other !== peek!.item.id));
    closePeek();
  }

  // --- Editing ---------------------------------------------------------
  let typed = $state("");
  let highlightIndex = $state(0);
  let creating = $state(false);
  let createError = $state<string | null>(null);
  let inputEl = $state<HTMLInputElement | null>(null);
  let rootEl = $state<HTMLElement | null>(null);

  const typedTrimmed = $derived(typed.trim());
  const candidates = $derived.by((): TagEntry[] => {
    const q = typedTrimmed.toLowerCase();
    if (!q) return [];
    const selected = new Set(ids);
    const pool = $liveTags.filter((t) => !selected.has(t.id) && (!fieldVocab || t.entry_type === fieldVocab));
    const matches = pool.filter((t) => t.title.toLowerCase().includes(q));
    matches.sort((a, b) => {
      const aStarts = a.title.toLowerCase().startsWith(q);
      const bStarts = b.title.toLowerCase().startsWith(q);
      if (aStarts !== bStarts) return aStarts ? -1 : 1;
      return a.title.localeCompare(b.title);
    });
    return matches.slice(0, 8);
  });
  // Minting is offered whenever the host names a layer to create in — `null`
  // means "this project" and is a valid layer; only `undefined` means the host
  // offers no create at all (the same contract ReferencePicker uses).
  const createEnabled = $derived(createLayerId !== undefined);
  // Never offer Create for a title already on the node: the candidates exclude
  // selected tags, so without this a retyped `night` would show `+ Create` and
  // silently no-op on Enter.
  const typedIsSelected = $derived(items.some((i) => i.title.trim().toLowerCase() === typedTrimmed.toLowerCase()));
  const canCreate = $derived(
    createEnabled &&
      createTarget != null &&
      typedTrimmed.length > 0 &&
      !typedIsSelected &&
      !hasTitleMatch(candidates, typedTrimmed),
  );
  const optionCount = $derived(candidates.length + (canCreate ? 1 : 0));
  // Combobox wiring: the listbox and its options carry ids so the input can
  // name the highlighted option for assistive tech.
  const listId = $derived(`tag-line-${fieldId}-list`);
  const listOpen = $derived(typedTrimmed.length > 0);
  const activeOptionId = $derived(
    !listOpen || optionCount === 0 ? undefined : highlightIndex < candidates.length ? `${listId}-${highlightIndex}` : `${listId}-create`,
  );

  $effect(() => {
    void typed;
    highlightIndex = 0;
  });

  $effect(() => {
    if (editing) void tick().then(() => inputEl?.focus());
  });

  $effect(() => {
    if (!editing) {
      typed = "";
      highlightIndex = 0;
      createError = null;
      creating = false;
    }
  });

  function moveHighlight(delta: number) {
    if (optionCount === 0) return;
    highlightIndex = (highlightIndex + delta + optionCount) % optionCount;
  }

  function pickCandidate(tag: TagEntry) {
    if (!ids.includes(tag.id)) onChange([...ids, tag.id]);
    typed = "";
  }

  async function createFromTyped() {
    if (!createTarget || creating || !typedTrimmed) return;
    creating = true;
    createError = null;
    try {
      const tag = await resolveOrCreateTag(typedTrimmed, createTarget.entryType, createLayerId ?? null);
      if (!ids.includes(tag.id)) onChange([...ids, tag.id]);
      typed = "";
    } catch (err) {
      createError = err instanceof Error ? err.message : "Couldn't create the tag.";
    } finally {
      creating = false;
    }
  }

  function commitHighlighted() {
    if (highlightIndex < candidates.length) {
      const tag = candidates[highlightIndex];
      if (tag) pickCandidate(tag);
      return;
    }
    if (canCreate) void createFromTyped();
  }

  async function closeAndRestoreFocus() {
    const rowEl = rootEl?.closest<HTMLElement>(".field-row") ?? null;
    onClose(fieldId);
    await tick();
    rowEl?.querySelector<HTMLElement>(".fr-rest-hit")?.focus();
  }

  function onInputKeydown(e: KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); moveHighlight(1); return; }
    if (e.key === "ArrowUp") { e.preventDefault(); moveHighlight(-1); return; }
    if (e.key === "Enter") {
      e.preventDefault();
      if (optionCount > 0) commitHighlighted();
      return;
    }
    if (e.key === "Backspace" && typed === "") {
      e.preventDefault();
      if (ids.length > 0) onChange(ids.slice(0, -1));
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      void closeAndRestoreFocus();
      return;
    }
    if ((e.key === "," || e.key === "·") && typedTrimmed.length > 0) {
      e.preventDefault();
      if (optionCount > 0) commitHighlighted();
    }
  }

  function onRootFocusOut(e: FocusEvent) {
    if (!(e.relatedTarget instanceof Node) || !rootEl?.contains(e.relatedTarget)) onClose(fieldId);
  }
</script>

{#snippet nameSpan(item: ResolvedTag, navigable: boolean)}{#if item.missing}<span class="tag-line-name missing">{item.title}</span>{:else if navigable}<button type="button" class="tag-line-name tag-line-navigate" data-tag-id={item.id} onclick={() => navigate(item.id, item.entryType)}>{item.title}</button>{:else}<span class="tag-line-name" data-tag-id={item.id}>{item.title}</span>{/if}{/snippet}

{#snippet lineBody(navigable: boolean)}{#if singleVocab}{#each items as item, i (item.id + i)}{#if i > 0}{" · "}{/if}{@render nameSpan(item, navigable)}{/each}{:else}{#each restGroups as group, gi (group.key)}{#if gi > 0}<span class="tag-line-divider">|</span>{/if}{#if group.label}<span class="tag-line-vocab">{`${group.label}: `}</span>{/if}{#each group.items as item, ii (item.id + ii)}{#if ii > 0}{" · "}{/if}{@render nameSpan(item, navigable)}{/each}{/each}{/if}{/snippet}

{#if readOnly}
  <span class="tag-line-hit" data-testid="rail-tag-line">
    {#if isEmpty}
      <span class="tag-line-add" aria-hidden="true">+</span>
    {:else}
      {@render lineBody(true)}
    {/if}
  </span>
{:else if editing}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="tag-line-hit tag-line-edit" bind:this={rootEl} onfocusout={onRootFocusOut}>
    <div class="tag-line-tokens">
      {#each items as item, i (item.id + i)}{#if i > 0}{" · "}{/if}<span class="tag-line-name" class:missing={item.missing}>{item.title}</span>{/each}{#if items.length > 0}{" · "}{/if}
      <input
        type="text"
        class="tag-line-input"
        role="combobox"
        aria-label={`Add ${fieldLabel}`}
        aria-autocomplete="list"
        aria-expanded={listOpen}
        aria-controls={listId}
        aria-activedescendant={activeOptionId}
        autocomplete="off"
        bind:value={typed}
        bind:this={inputEl}
        onkeydown={onInputKeydown}
      />
    </div>
    {#if typedTrimmed.length > 0}
      <ul role="listbox" id={listId} class="tag-line-complete">
        {#each candidates as candidate, i (candidate.id)}
          <li
            role="option"
            id={`${listId}-${i}`}
            aria-selected={i === highlightIndex}
            class="tag-line-option"
            class:highlighted={i === highlightIndex}
            onmousedown={(e) => { e.preventDefault(); pickCandidate(candidate); }}
          >
            <span>{candidate.title}</span>
            {#if !fieldVocab}<span class="tag-line-option-vocab">{vocabLabel(candidate.entry_type)}</span>{/if}
          </li>
        {/each}
        {#if canCreate}
          <li
            role="option"
            id={`${listId}-create`}
            data-testid="tag-line-create"
            aria-selected={candidates.length === highlightIndex}
            class="tag-line-option"
            class:highlighted={candidates.length === highlightIndex}
            onmousedown={(e) => { e.preventDefault(); void createFromTyped(); }}
          >+ Create "{typedTrimmed}"</li>
        {/if}
      </ul>
    {/if}
    {#if createError}<p class="tag-line-error" role="alert">{createError}</p>{/if}
  </div>
{:else}
  <button
    type="button"
    class="fr-rest-hit tag-line-hit"
    data-testid="rail-tag-line"
    aria-label={ariaLabel}
    title={field.description || (isEmpty ? `Set ${fieldLabel}` : `Edit ${fieldLabel}`)}
    onclick={(e) => onOpen(fieldId, (e.currentTarget as HTMLElement).closest(".field-row") as HTMLElement)}
    use:peekAnchor={{ delegate: ".tag-line-name[data-tag-id]", onOpen: openPeek, onClose: closePeek }}
  >
    {#if isEmpty}
      <span class="tag-line-add" aria-hidden="true">+</span>
    {:else}
      {@render lineBody(false)}
    {/if}
  </button>
{/if}

{#if peek && peekModel}
  <PeekCard
    model={peekModel}
    anchor={peek.anchor}
    {field}
    on={{
      open: () => navigate(peek!.item.id, peek!.item.entryType),
      remove: readOnly ? undefined : peekRemove,
      close: closePeek,
    }}
  />
{/if}

<style>
  .tag-line-hit {
    display: block;
    font-family: var(--mono);
    font-size: var(--fs-sm);
    color: var(--text-2);
    line-height: 1.6;
    overflow-wrap: anywhere;
    text-align: left;
  }
  .fr-rest-hit {
    width: 100%;
    border: 0;
    background: transparent;
    padding: 2px 4px;
    margin: 0;
    border-radius: var(--r-sm);
    cursor: pointer;
  }
  .fr-rest-hit:hover { background: color-mix(in srgb, var(--inset) 70%, transparent); }
  .fr-rest-hit:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }

  .tag-line-add { color: var(--text-3); font-size: var(--fs-lg); line-height: 1; }

  .tag-line-vocab { color: var(--text-3); margin-right: 4px; }
  .tag-line-divider { color: var(--text-3); margin: 0 6px; }
  .missing { color: var(--danger); }

  .tag-line-navigate {
    border: none;
    background: none;
    padding: 0;
    margin: 0;
    font: inherit;
    color: inherit;
    cursor: pointer;
  }
  .tag-line-navigate:hover { text-decoration: underline; }

  /* The edit state keeps the rest line's shape (#2059): the tokens with the
     input at their end, on the same line(s) as the names, and the completion
     list FLOATING under that line rather than laid out in flow — so the row
     never grows past its token line and nothing below it moves while a tag
     is typed (in the front matter the prose used to shift 73px). */
  .tag-line-edit { position: relative; }
  .tag-line-tokens { display: flex; flex-wrap: wrap; align-items: baseline; }

  .tag-line-tokens > .tag-line-input {
    font: inherit;
    border: none;
    border-bottom: 1px solid var(--accent);
    background: none;
    /* Sized to its text, never to the line. The global text-input rule
       (styles.css, `input:not([type=checkbox]):not([type=radio])`) sets
       `width: 100%` at a specificity a lone class cannot beat, which put the
       input on a line of its own at full width; the parent-qualified selector
       outranks it. */
    field-sizing: content;
    flex: 0 1 auto;
    min-width: 6ch;
    max-width: 100%;
    width: auto;
    margin: 0;
    padding: 0 2px;
    color: var(--text);
    outline: none;
  }

  .tag-line-complete {
    position: absolute;
    top: 100%;
    left: 0;
    z-index: var(--z-dropdown);
    min-width: 220px;
    max-width: 100%;
    max-height: 40vh;
    overflow: auto;
    margin: 2px 0 0;
    padding: 2px 0;
    list-style: none;
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    background: var(--surface);
    box-shadow: var(--elev-1);
    font-family: var(--sans);
  }
  .tag-line-option { padding: 3px 8px; cursor: pointer; }
  .tag-line-option.highlighted { background: var(--accent-soft); color: var(--accent-emphasis); }
  .tag-line-option-vocab { color: var(--text-3); margin-left: 6px; }

  .tag-line-error { color: var(--danger); font-size: var(--fs-xs); margin: 2px 0 0; }
</style>
