<!--
  OfferOnPicker — the "Show in ＋New on…" authoring control for a chat_panel
  prompt (ADR-0054 §4 / S4b). Writes the instance-level `offer_on` allow-list:
  the subject entry_types on which this prompt is offered as a ＋New conversation
  in a node's Conversations panel (read back by `promptEntriesOfferedOn`).

  A plain multi-select of concrete entry_types grouped by kind — no is-a
  expansion here, since offer_on is stored as exact ids and the is-a match
  happens at read time (`promptOffersOn`). Mounted by CodeBodyView ONLY when the
  open prompt resolves to a `chat_panel` disposition (the only kind ＋New lists),
  so a control that would do nothing is never shown. The picker itself is
  disposition-agnostic; the gate lives in the host.

  `offer_on` is bind:'d to the parent (NodeEditor's offerOnDraft) so the parent's
  save logic owns serialization; `onChange` fires the pane's emitChange.
-->
<script lang="ts">
  import type { MetadataSchema } from "@/lib/types";

  interface Props {
    metadataSchema: MetadataSchema | null;
    // Persisted shape (bind:'d by the parent) — exact entry_type ids.
    offerOn?: string[];
    // Locked for a built-in Library prompt (the host also wraps us in `inert`).
    readOnly?: boolean;
    // Outbound: the allow-list changed → parent emits its change/save.
    onChange?: () => void;
  }

  let {
    metadataSchema = null,
    offerOn = $bindable([]),
    readOnly = false,
    onChange,
  }: Props = $props();

  // The kinds whose nodes actually mount a Conversations ＋New menu — the only
  // subjects an offer_on target can ever reach. Mirrors NodeEditor's
  // `conversationsKind` gate (document kinds lore / scene / plot_card) at the
  // schema-kind granularity (plot_card ∈ kind "plot"). Offering any other kind
  // (view / assistant / research / project / mutation_set) would be dead config:
  // the write succeeds but no such node ever shows the prompt.
  const HOST_KINDS = new Set(["lore", "scene", "plot"]);

  // Concrete, offerable subject types grouped by kind. Abstract and deprecated
  // types are dropped (never offered for new work); so is any kind that doesn't
  // host a conversation. A writer leaves unrelated ones unchecked.
  const groups = $derived.by(() => {
    const schema = metadataSchema;
    if (!schema) return [] as { kind: string; items: { id: string; name: string }[] }[];
    const byKind = new Map<string, { id: string; name: string }[]>();
    for (const [id, def] of Object.entries(schema.entry_types)) {
      if (def.abstract || def.deprecated) continue;
      if (!HOST_KINDS.has(def.kind)) continue;
      const list = byKind.get(def.kind) ?? [];
      list.push({ id, name: def.name || id });
      byKind.set(def.kind, list);
    }
    return [...byKind.entries()]
      .map(([kind, items]) => ({
        kind,
        items: items.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" })),
      }))
      .sort((a, b) => a.kind.localeCompare(b.kind, undefined, { sensitivity: "base" }));
  });

  function isChecked(id: string): boolean {
    return offerOn.includes(id);
  }

  function toggle(id: string, checked: boolean): void {
    if (readOnly) return;
    if (checked) {
      if (!offerOn.includes(id)) offerOn = [...offerOn, id];
    } else {
      offerOn = offerOn.filter((target) => target !== id);
    }
    onChange?.();
  }

  // Capitalise a kind slug for its group heading ("lore" → "Lore").
  function kindLabel(kind: string): string {
    return kind.charAt(0).toUpperCase() + kind.slice(1);
  }
</script>

<details class="offer-on-editor">
  <summary>
    Show in ＋New <small>{offerOn.length}</small>
    <small class="offer-on-hint">this conversation is offered on the checked subjects · a subtype matches its parent</small>
  </summary>
  {#if groups.length === 0}
    <p class="muted offer-on-empty">No subject types defined yet.</p>
  {:else}
    {#each groups as group (group.kind)}
      <div class="offer-on-group" role="group" aria-label={kindLabel(group.kind)}>
        <h5 class="offer-on-group-title">{kindLabel(group.kind)}</h5>
        {#each group.items as item (item.id)}
          <label class="offer-on-option">
            <input
              type="checkbox"
              checked={isChecked(item.id)}
              disabled={readOnly}
              onchange={(e) => toggle(item.id, (e.currentTarget as HTMLInputElement).checked)}
            />
            <span class="offer-on-option-name">{item.name}</span>
            <code class="offer-on-option-id">{item.id}</code>
          </label>
        {/each}
      </div>
    {/each}
  {/if}
</details>

<style>
  /* Mirrors EntryInputsEditor's disclosure chrome so the two prompt sidecars
     read as a set (same inset panel, summary weight, hint colour). */
  .offer-on-editor {
    padding: 6px 12px;
    background: var(--inset);
    border-top: 1px solid var(--border);
    font-size: var(--fs-md);
  }
  .offer-on-editor[open] {
    max-height: 40vh;
    overflow-y: auto;
  }
  .offer-on-editor > summary {
    cursor: pointer;
    user-select: none;
    font-weight: 600;
    color: var(--text);
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .offer-on-editor > summary > small {
    color: var(--text-3);
    font-weight: 400;
  }
  .offer-on-hint {
    margin-left: auto;
    font-size: var(--fs-xs);
    text-align: right;
  }
  .offer-on-empty {
    margin: 6px 0;
    font-size: var(--fs-sm);
  }
  .offer-on-group {
    margin: 8px 0 4px;
  }
  .offer-on-group-title {
    margin: 0 0 4px;
    font-size: var(--fs-xs);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-2);
  }
  .offer-on-option {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 3px 6px;
    border-radius: 4px;
    cursor: pointer;
    font-size: var(--fs-sm);
    color: var(--text);
  }
  .offer-on-option:hover {
    background: var(--surface);
  }
  .offer-on-option > input {
    margin: 0;
    align-self: center;
  }
  .offer-on-option-name {
    font-weight: 500;
  }
  .offer-on-option-id {
    margin-left: auto;
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--text-3);
    background: var(--surface);
    border: 1px solid var(--divider);
    border-radius: 4px;
    padding: 0 6px;
  }
</style>
