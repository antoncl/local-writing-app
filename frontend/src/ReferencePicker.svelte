<script lang="ts">
  import { createEventDispatcher, onMount, tick } from "svelte";
  import { api } from "./api";
  import type { MetadataFieldDefinition, MetadataSchema, ReferenceCandidate } from "./types";

  export let field: MetadataFieldDefinition;
  export let value: string | string[] | null | undefined;
  export let metadataSchema: MetadataSchema | null = null;
  export let excludeId: string | null = null;
  export let ariaLabel: string = "";

  const dispatch = createEventDispatcher<{ change: { value: string | string[] } }>();

  $: multi = field.type === "entity_ref_list";
  $: selectedIds = toIdList(value);
  $: targetEntryType = field.target?.entry_type ?? "";
  $: pickerKind = resolvePickerKind(field, metadataSchema);

  function resolvePickerKind(currentField: MetadataFieldDefinition, schema: MetadataSchema | null) {
    const explicitKind = currentField.target?.kind;
    if (explicitKind) return explicitKind;
    const entryTypeId = currentField.target?.entry_type;
    if (entryTypeId && schema?.entry_types[entryTypeId]) {
      return schema.entry_types[entryTypeId].kind;
    }
    return "";
  }

  type ResolvedCandidate = ReferenceCandidate & { displayTitle: string };

  let resolved: Record<string, ResolvedCandidate> = {};
  let resolveToken = 0;
  let dropdownOpen = false;
  let dropdownLoading = false;
  let dropdownError = "";
  let candidates: ReferenceCandidate[] = [];
  let searchText = "";
  let pickerEl: HTMLDivElement | null = null;
  let dropdownEl: HTMLDivElement | null = null;
  let searchInput: HTMLInputElement | null = null;

  $: void refreshResolved(selectedIds);

  function toIdList(input: string | string[] | null | undefined): string[] {
    if (input === null || input === undefined) return [];
    if (Array.isArray(input)) {
      return input.map((item) => String(item).trim()).filter(Boolean);
    }
    const trimmed = String(input).trim();
    return trimmed ? [trimmed] : [];
  }

  async function refreshResolved(ids: string[]) {
    const token = ++resolveToken;
    const missing = ids.filter((id) => !resolved[id]);
    if (missing.length === 0) {
      pruneResolved(ids);
      return;
    }
    try {
      const response = await api.resolveReferences(missing);
      if (token !== resolveToken) return;
      const next = { ...resolved };
      for (const candidate of response.candidates) {
        next[candidate.id] = { ...candidate, displayTitle: candidate.found ? candidate.title : candidate.id };
      }
      resolved = next;
      pruneResolved(ids);
    } catch (error) {
      console.warn("Failed to resolve references", error);
    }
  }

  function pruneResolved(ids: string[]) {
    const next: Record<string, ResolvedCandidate> = {};
    for (const id of ids) {
      if (resolved[id]) next[id] = resolved[id];
    }
    resolved = next;
  }

  function entryTypeLabel(entryTypeId: string) {
    if (!entryTypeId) return "";
    return metadataSchema?.entry_types[entryTypeId]?.name ?? entryTypeId;
  }

  function emit(nextIds: string[]) {
    if (multi) {
      dispatch("change", { value: nextIds });
    } else {
      dispatch("change", { value: nextIds[0] ?? "" });
    }
  }

  function removeId(id: string) {
    emit(selectedIds.filter((candidate) => candidate !== id));
  }

  async function openDropdown() {
    dropdownOpen = true;
    dropdownLoading = true;
    dropdownError = "";
    searchText = "";
    try {
      const response = await api.listReferenceCandidates({
        kind: pickerKind || undefined,
        entry_type: targetEntryType || undefined,
        exclude_id: excludeId || undefined,
      });
      candidates = response.candidates;
    } catch (error) {
      dropdownError = error instanceof Error ? error.message : String(error);
      candidates = [];
    } finally {
      dropdownLoading = false;
      await tick();
      searchInput?.focus();
      dropdownEl?.scrollIntoView({ block: "nearest" });
    }
  }

  function closeDropdown() {
    dropdownOpen = false;
    candidates = [];
  }

  function chooseCandidate(candidate: ReferenceCandidate) {
    if (multi) {
      if (!selectedIds.includes(candidate.id)) {
        emit([...selectedIds, candidate.id]);
      }
    } else {
      emit([candidate.id]);
      closeDropdown();
    }
  }

  $: filteredCandidates = filterCandidates(candidates, searchText, selectedIds);
  $: groupedCandidates = groupByEntryType(filteredCandidates);

  function filterCandidates(list: ReferenceCandidate[], query: string, selected: string[]) {
    const needle = query.trim().toLowerCase();
    const selectedSet = new Set(selected);
    return list.filter((candidate) => {
      if (multi && selectedSet.has(candidate.id)) return false;
      if (!needle) return true;
      return candidate.title.toLowerCase().includes(needle) || candidate.id.toLowerCase().includes(needle);
    });
  }

  function groupByEntryType(list: ReferenceCandidate[]) {
    const groups = new Map<string, ReferenceCandidate[]>();
    for (const candidate of list) {
      const bucket = groups.get(candidate.entry_type) ?? [];
      bucket.push(candidate);
      groups.set(candidate.entry_type, bucket);
    }
    return Array.from(groups.entries()).map(([entryType, items]) => ({
      entryType,
      label: entryTypeLabel(entryType),
      items,
    }));
  }

  function handleDocumentClick(event: MouseEvent) {
    if (!dropdownOpen || !pickerEl) return;
    if (event.target instanceof Node && !pickerEl.contains(event.target)) {
      closeDropdown();
    }
  }

  function handleKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape" && dropdownOpen) {
      event.preventDefault();
      closeDropdown();
    }
  }

  onMount(() => {
    document.addEventListener("mousedown", handleDocumentClick);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleDocumentClick);
      document.removeEventListener("keydown", handleKeyDown);
    };
  });
</script>

<div class="reference-picker" aria-label={ariaLabel} bind:this={pickerEl}>
  {#if selectedIds.length > 0}
    <div class="reference-cards">
      {#each selectedIds as id (id)}
        {@const entry = resolved[id]}
        <div class:missing={entry && !entry.found} class="reference-card">
          <div class="reference-card-main">
            <span class="reference-card-title">{entry ? entry.displayTitle : id}</span>
            {#if entry && entry.found}
              <span class="reference-card-type">{entryTypeLabel(entry.entry_type)}</span>
              {#if entry.summary}
                <span class="reference-card-summary">{entry.summary}</span>
              {/if}
            {:else if entry && !entry.found}
              <span class="reference-card-summary">Missing reference</span>
            {/if}
          </div>
          <button class="reference-card-remove" type="button" title="Remove" on:click={() => removeId(id)}>×</button>
        </div>
      {/each}
    </div>
  {/if}

  {#if multi || selectedIds.length === 0}
    <button class="reference-add-button" type="button" on:click={() => (dropdownOpen ? closeDropdown() : openDropdown())}>
      {selectedIds.length === 0 ? "+ Add reference" : "+ Add another"}
    </button>
  {:else}
    <button class="reference-add-button" type="button" on:click={() => (dropdownOpen ? closeDropdown() : openDropdown())}>
      Change reference
    </button>
  {/if}

  {#if dropdownOpen}
    <div class="reference-dropdown" bind:this={dropdownEl}>
      <input
        bind:this={searchInput}
        bind:value={searchText}
        class="reference-search"
        type="text"
        placeholder="Search"
        aria-label="Search references"
      />
      {#if dropdownLoading}
        <div class="reference-empty">Loading…</div>
      {:else if dropdownError}
        <div class="reference-empty reference-error">{dropdownError}</div>
      {:else if candidates.length === 0}
        <div class="reference-empty">No {entryTypeLabel(targetEntryType) || pickerKind || "entries"} yet</div>
      {:else if groupedCandidates.length === 0}
        <div class="reference-empty">No matches</div>
      {:else}
        <div class="reference-results">
          {#each groupedCandidates as group (group.entryType)}
            <div class="reference-group-label">{group.label}</div>
            {#each group.items as candidate (candidate.id)}
              <button
                class="reference-option"
                type="button"
                on:mousedown|preventDefault
                on:click={() => chooseCandidate(candidate)}
              >
                <span class="reference-option-title">{candidate.title}</span>
                {#if candidate.summary}
                  <span class="reference-option-summary">{candidate.summary}</span>
                {/if}
              </button>
            {/each}
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .reference-picker {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .reference-cards {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .reference-card {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 6px 8px;
    border: 1px solid #dfe6e3;
    border-radius: 6px;
    background: #f7faf8;
  }

  .reference-card.missing {
    border-color: #c98a8a;
    background: #fbeeee;
  }

  .reference-card-main {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    gap: 2px;
  }

  .reference-card-title {
    font-weight: 600;
    font-size: 13px;
    color: #1f4d41;
  }

  .reference-card-type {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #65716c;
  }

  .reference-card-summary {
    font-size: 12px;
    color: #4a5450;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .reference-card-remove {
    border: none;
    background: transparent;
    color: #65716c;
    cursor: pointer;
    font-size: 16px;
    line-height: 1;
    padding: 2px 6px;
  }

  .reference-card-remove:hover {
    color: #1f4d41;
  }

  .reference-add-button {
    align-self: flex-start;
    padding: 4px 10px;
    font-size: 12px;
    border: 1px dashed #b8c3be;
    border-radius: 6px;
    background: transparent;
    color: #1f4d41;
    cursor: pointer;
  }

  .reference-add-button:hover {
    border-style: solid;
    background: #edf6f2;
  }

  .reference-dropdown {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    z-index: 10000;
    width: min(320px, calc(100vw - 24px));
    max-height: min(320px, calc(100vh - 24px));
    display: flex;
    flex-direction: column;
    border: 1px solid #dfe6e3;
    border-radius: 6px;
    background: #ffffff;
    box-shadow: 0 10px 24px rgba(36, 48, 43, 0.18);
  }

  .reference-search {
    display: block;
    margin: 8px;
    padding: 6px 8px;
    width: calc(100% - 16px);
    box-sizing: border-box;
    font-size: 13px;
    border: 1px solid #dfe6e3;
    border-radius: 4px;
  }

  .reference-results {
    overflow: auto;
    padding: 4px 0 8px;
  }

  .reference-group-label {
    padding: 6px 12px 2px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #65716c;
  }

  .reference-option {
    display: flex;
    flex-direction: column;
    gap: 2px;
    width: 100%;
    padding: 6px 12px;
    border: none;
    background: transparent;
    text-align: left;
    cursor: pointer;
  }

  .reference-option:hover {
    background: #edf6f2;
  }

  .reference-option-title {
    font-size: 13px;
    color: #1f4d41;
  }

  .reference-option-summary {
    font-size: 11px;
    color: #65716c;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .reference-empty {
    padding: 12px;
    font-size: 12px;
    color: #65716c;
    text-align: center;
  }

  .reference-empty.reference-error {
    color: #a64a4a;
  }
</style>
