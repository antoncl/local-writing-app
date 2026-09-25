<script lang="ts">
  // ADR-0089 Amendment 2 (#2221): the reference-list detail line IS the
  // item's editor. One clickable segment per non-key member, joined by
  // " · " (design record: docs/design/mockups/0089-detail-line-editor.html).
  // An empty member shows its own name, muted+italic, as the placeholder
  // (replaces #2218's "Add details…"). `text`/`number` edit inline; `select`/
  // `color` render FieldValueEditor's own widget in place, `autoOpen`, so
  // their option list opens in ONE click; every other type opens a popover
  // wrapped around the rail's own FieldValueEditor — no new widget, per the
  // amendment's anti-goals.
  //
  // Editing state (which member, if any, is open) is owned by the CALLER
  // (ReferenceListTab), not here: only one segment edits at a time across
  // the whole tab, and that requires comparing across sibling row instances
  // of this component. `editingKey` is this item's own open member (or
  // null); `onEditStart`/`onEditEnd` ask the caller to move/close it.
  import { tick } from "svelte";
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import { anchoredPopover } from "@/lib/actions/anchoredPopover";
  import { isMetadataValuePresent, metadataValueDisplayString } from "@/lib/utils/schemaTypeHelpers";
  import type { GroupMember } from "@/lib/schemaTypes";
  import type {
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataValue,
    NavigateTarget,
    PromptEntrySummary,
    StructureDocument,
  } from "@/lib/types";
  import type { CompiledMatcher } from "@/lib/editor-core/implicitContextMatcher";

  // `text`/`number` edit in place as a plain input; every other member type
  // opens the popover instead (ADR-0089 Amendment 2, decision 3).
  const INLINE_TYPES = new Set(["text", "number"]);
  // `select`/`color` render FieldValueEditor's own widget (ColoredSelect /
  // SwatchPicker) DIRECTLY in the segment's place, `autoOpen`, instead of
  // wrapping it in a second popover — the approved design requires their
  // option list to open in ONE click, anchored on the segment (#2221 follow-
  // up); those two widgets already own a trigger + a body-portaled popover,
  // so a wrapper wraps a popover around a popover-owning trigger.
  const AUTO_OPEN_TYPES = new Set(["select", "color"]);
  // A "continuous" popover type keeps picking after one commit (multiple
  // options, a long text still being typed) — everything else closes the
  // popover the moment `onChange` fires, mirroring the mockup's select.
  const CONTINUOUS_TYPES = new Set(["multi_select", "long_text"]);

  interface Deps {
    loreEntries: LoreEntrySummary[];
    promptEntries: PromptEntrySummary[];
    structure: StructureDocument | null;
    researchStructure: StructureDocument | null;
    excludeId?: string | null;
    createLayerId?: string | null;
    implicitContextMatcher?: CompiledMatcher | null;
  }

  interface Props {
    // The item's NON-key members, in item_members order — the key member is
    // never a segment (ADR-0089 Amendment 2, decision 5).
    members: GroupMember[];
    record: Record<string, MetadataValue>;
    editable: boolean;
    // This item's currently-open member key, or null — null while scrubbed
    // (segments render as plain text) or while another item's segment holds
    // the tab's one open edit.
    editingKey: string | null;
    deps: Deps;
    onEditStart: (key: string) => void;
    onEditEnd: (key: string) => void;
    onCommit: (key: string, value: MetadataValue) => void;
    onNavigate?: (target: NavigateTarget) => void;
  }

  let { members, record, editable, editingKey, deps, onEditStart, onEditEnd, onCommit, onNavigate }: Props = $props();

  function memberField(member: GroupMember): MetadataFieldDefinition {
    return {
      name: member.name || member.key,
      type: member.type,
      options: member.options ?? [],
      picker_config: member.picker_config ?? null,
    };
  }

  function displayFor(member: GroupMember): string {
    const display = metadataValueDisplayString(record[member.key] ?? null);
    return member.type === "long_text" ? display.split("\n")[0] : display;
  }

  // --- inline text/number edit --------------------------------------------
  let draft = $state("");
  let inputEl = $state<HTMLInputElement>();

  function beginEdit(member: GroupMember) {
    if (!editable) return;
    if (INLINE_TYPES.has(member.type)) draft = displayFor(member);
    onEditStart(member.key);
  }

  $effect(() => {
    if (editingKey && inputEl) {
      inputEl.focus();
      inputEl.select();
    }
  });

  function inlineValue(member: GroupMember): MetadataValue {
    if (member.type === "number") {
      const trimmed = draft.trim();
      if (trimmed === "") return null;
      const parsed = Number(trimmed);
      return Number.isFinite(parsed) ? parsed : null;
    }
    // `text` matches FieldValueEditor's own commit (no trimming — the rail's
    // plain text input keeps exactly what was typed).
    return draft;
  }

  function commitInline(member: GroupMember) {
    onCommit(member.key, inlineValue(member));
  }

  function nextMemberKey(fromKey: string, dir: 1 | -1): string | null {
    const index = members.findIndex((m) => m.key === fromKey);
    const next = members[index + dir];
    return next ? next.key : null;
  }

  function handleInlineKeydown(event: KeyboardEvent, member: GroupMember) {
    if (event.key === "Enter") {
      commitInline(member);
      onEditEnd(member.key);
    } else if (event.key === "Escape") {
      onEditEnd(member.key); // revert: no commit
    } else if (event.key === "Tab") {
      event.preventDefault();
      commitInline(member);
      const nextKey = nextMemberKey(member.key, event.shiftKey ? -1 : 1);
      const next = nextKey ? members.find((m) => m.key === nextKey) : undefined;
      if (next) void openNext(next);
      else onEditEnd(member.key); // past the last (or before the first): commit and exit
    }
  }

  async function openNext(member: GroupMember) {
    // Seed the inline draft off the CURRENT record (this member's value is
    // untouched by the commit above unless it's the same member) before the
    // caller reassigns `editingKey` — matches `beginEdit`'s own seeding.
    if (INLINE_TYPES.has(member.type)) draft = displayFor(member);
    onEditStart(member.key);
    await tick();
  }

  function handleInlineBlur(member: GroupMember) {
    // A click on a different segment (or outside) moves focus away — commit
    // what was typed, same as any other autosave field. A programmatic
    // Tab/Enter/Escape transition already called onEditEnd itself, so this
    // only fires for a genuine blur.
    if (editingKey === member.key) {
      commitInline(member);
      onEditEnd(member.key);
    }
  }

  // --- popover (every other type) ------------------------------------------
  let segmentEls: Record<string, HTMLButtonElement | undefined> = {};

  function handlePopoverChange(member: GroupMember, value: MetadataValue) {
    onCommit(member.key, value);
    if (!CONTINUOUS_TYPES.has(member.type)) onEditEnd(member.key);
  }

  $effect(() => {
    const key = editingKey;
    if (!key) return;
    const member = members.find((m) => m.key === key);
    // Inline commits via blur; an auto-open widget owns its own Esc/outside-
    // click close (wired to `onEditEnd` via `onPopoverClose` below) — a
    // second listener here would double-close it (and, worse, treat a click
    // INSIDE its own portaled popover as "outside", since that popover isn't
    // `.idl-popover`).
    if (!member || INLINE_TYPES.has(member.type) || AUTO_OPEN_TYPES.has(member.type)) return;
    function onDocClick(event: MouseEvent) {
      const target = event.target as Node | null;
      const trigger = segmentEls[key!];
      if (target && trigger && trigger.contains(target)) return;
      const pop = document.querySelector(".idl-popover");
      if (pop && target && pop.contains(target)) return;
      onEditEnd(key!);
    }
    function onKeydown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onEditEnd(key!);
      }
    }
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKeydown);
    return () => {
      document.removeEventListener("click", onDocClick);
      document.removeEventListener("keydown", onKeydown);
    };
  });
</script>

<span class="idl-segments">
  {#each members as member, i (member.key)}
    {#if i > 0}<span class="idl-sep">·</span>{/if}
    {@const empty = !isMetadataValuePresent(record[member.key])}
    {@const label = member.name || member.key}
    {#if !editable}
      <span class="idl-seg" class:idl-empty={empty} title={label}>{empty ? label : displayFor(member)}</span>
    {:else if editingKey === member.key && INLINE_TYPES.has(member.type)}
      <input
        class="idl-input"
        bind:this={inputEl}
        value={draft}
        aria-label={label}
        oninput={(event) => (draft = event.currentTarget.value)}
        onkeydown={(event) => handleInlineKeydown(event, member)}
        onblur={() => handleInlineBlur(member)}
      />
    {:else if editingKey === member.key && AUTO_OPEN_TYPES.has(member.type)}
      <span class="idl-seg idl-seg-inline-editor">
        <FieldValueEditor
          field={memberField(member)}
          value={record[member.key] ?? null}
          ariaLabel={label}
          onChange={(value) => onCommit(member.key, value)}
          autoOpen
          onPopoverClose={() => onEditEnd(member.key)}
          loreEntries={deps.loreEntries}
          promptEntries={deps.promptEntries}
          structure={deps.structure}
          researchStructure={deps.researchStructure}
          excludeId={deps.excludeId ?? null}
          createLayerId={deps.createLayerId ?? undefined}
          implicitContextMatcher={deps.implicitContextMatcher ?? null}
          onNavigate={onNavigate}
        />
      </span>
    {:else}
      <button
        type="button"
        class="idl-seg idl-seg-btn"
        class:idl-empty={empty}
        class:idl-editing={editingKey === member.key}
        title={label}
        aria-label={empty ? label : `${label}: ${displayFor(member)}`}
        bind:this={segmentEls[member.key]}
        onclick={() => beginEdit(member)}
      >{empty ? label : displayFor(member)}</button>
      {#if editingKey === member.key}
        <div class="idl-popover" role="dialog" aria-label={label} use:anchoredPopover={{ anchor: segmentEls[member.key], gap: 4 }}>
          <FieldValueEditor
            field={memberField(member)}
            value={record[member.key] ?? null}
            ariaLabel={label}
            onChange={(value) => handlePopoverChange(member, value)}
            loreEntries={deps.loreEntries}
            promptEntries={deps.promptEntries}
            structure={deps.structure}
            researchStructure={deps.researchStructure}
            excludeId={deps.excludeId ?? null}
            createLayerId={deps.createLayerId ?? undefined}
            implicitContextMatcher={deps.implicitContextMatcher ?? null}
            onNavigate={onNavigate}
          />
        </div>
      {/if}
    {/if}
  {/each}
</span>

<style>
  .idl-segments {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
  }

  .idl-sep {
    color: var(--text-3);
    padding: 0 3px;
  }

  .idl-seg {
    display: inline-block;
    border-radius: var(--r-sm);
    padding: 0 2px;
    border: 1px solid transparent;
    color: inherit;
    font: inherit;
    background: none;
  }

  button.idl-seg {
    cursor: pointer;
  }

  button.idl-seg:hover,
  button.idl-seg.idl-editing {
    border-color: var(--border);
    background: var(--inset);
  }

  button.idl-seg:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }

  .idl-empty {
    color: var(--text-3);
    font-style: italic;
  }

  /* select/color: FieldValueEditor's own trigger (ColoredSelect/SwatchPicker)
     sits right where the segment button was — no border/padding of its own
     here, that widget supplies its own chrome. */
  .idl-seg-inline-editor {
    display: inline-flex;
    align-items: center;
  }

  .idl-input {
    font: inherit;
    font-size: var(--fs-sm);
    padding: 0 3px;
    border: 1px solid var(--accent);
    border-radius: var(--r-sm);
    background: var(--surface);
    color: var(--text);
    /* Sized to its content so an edit stays on the detail line; it wraps only
       when the line is genuinely full. */
    field-sizing: content;
    min-width: 4em;
    max-width: 100%;
  }

  .idl-popover {
    z-index: 10000;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px;
    box-shadow: var(--elev-2);
    min-width: 180px;
  }
</style>
