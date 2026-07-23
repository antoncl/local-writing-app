<script lang="ts">
  // Machine-settings dialog. Holds the editing UI for the user's
  // machine config: default folder, provider API keys, Ollama host,
  // and the color palette editor. The parent loads / persists the
  // draft; this component owns only the local mutations on the draft
  // it's been handed.
  import type { MachineSettingsDraft, MachineSettingsView, Swatch } from "@/lib/types";
  import Modal from "@/components/dialogs/Modal.svelte";

  export let open: boolean = false;
  // The persisted view (read-only here — used for `config_path` and
  // any context that shouldn't be edited inline).
  export let settings: MachineSettingsView | null = null;
  // The editable draft. Two-way bound so the parent sees changes to
  // text inputs and the palette without needing per-field callbacks.
  export let draft: MachineSettingsDraft | null = null;
  export let onCancel: () => void = () => {};
  export let onSave: () => void = () => {};

  function paletteAddSwatch() {
    if (!draft) return;
    const baseId = "new-color";
    const existing = new Set(draft.palette.map((s) => s.id));
    let id = baseId;
    let n = 2;
    while (existing.has(id)) id = `${baseId}-${n++}`;
    draft.palette = [
      ...draft.palette,
      { id, label: "New color", hex: "#888888" },
    ];
  }

  function paletteRemoveSwatch(index: number) {
    if (!draft) return;
    draft.palette = draft.palette.filter((_, i) => i !== index);
  }

  function paletteMoveSwatch(from: number, to: number) {
    if (!draft) return;
    const list = draft.palette.slice();
    const [moved] = list.splice(from, 1);
    list.splice(to, 0, moved);
    draft.palette = list;
  }

  function paletteSetSwatch(index: number, patch: Partial<Swatch>) {
    if (!draft) return;
    draft.palette = draft.palette.map((s, i) =>
      i === index ? { ...s, ...patch } : s,
    );
  }
</script>

{#if open && draft}
  <Modal
    title="Machine Settings"
    label="Machine settings"
    frameClass="machine-settings-modal"
    frameStyle="--modal-width: min(640px, calc(100vw - 48px)); --modal-max-height: calc(100vh - 80px); --modal-overflow-y: auto;"
  >
      <p class="muted">Your AI subscriptions — provider accounts and keys.</p>
      <p class="muted">Stored locally at: <code>{settings?.config_path}</code></p>

      <label>
        Projects folder
        <div class="path-picker-row">
          <input type="text" bind:value={draft.default_projects_folder} placeholder="C:\path\to\writing" />
          <button
            type="button"
            disabled={!draft.default_projects_folder}
            on:click={() => draft && (draft.default_projects_folder = "")}
          >Clear</button>
        </div>
        <!--
          The copy here used to describe this as a creation convenience only.
          Since #429 it is also the outer bound of every project's inheritance
          chain, so clearing it is not a neutral "ask me each time" — it stops
          every project inheriting. Saying so is the difference between an
          informed choice and a silent, machine-wide loss of schema, assistants
          and lore. The label lost "Default" for the same reason: the value is
          authoritative, not a suggestion.
        -->
        <small class="muted">
          The one folder this app works within. New projects are created here, and a project
          inherits from the projects above it up to this folder — so widening it deepens every
          chain at once. Leave empty and each project stands alone, inheriting nothing. The
          project switcher reads recent projects from this config too.
        </small>
      </label>

      <p class="muted">API keys are masked on read. Leaving a masked field unchanged keeps the existing value.</p>

      <label>
        Anthropic API key
        <input type="password" autocomplete="off" bind:value={draft.anthropic_api_key} placeholder="sk-ant-…" />
      </label>
      <label>
        OpenAI API key
        <input type="password" autocomplete="off" bind:value={draft.openai_api_key} placeholder="sk-…" />
      </label>
      <label>
        OpenRouter API key
        <input type="password" autocomplete="off" bind:value={draft.openrouter_api_key} placeholder="sk-or-…" />
      </label>
      <label>
        Ollama host
        <input type="text" bind:value={draft.ollama_host} placeholder="http://127.0.0.1:11434" />
      </label>

      <p class="muted">
        Assistants moved to the <strong>Assistants</strong> pane (open from the AI section of the Project pane). Each lives as its own file under the machine config dir and can be overridden by ancestor projects.
      </p>

      <section class="palette-editor">
        <h3>Color palette</h3>
        <p class="muted">
          Colors picked here are reusable across types, entries, and select options. The first four (Forest, Slate Blue, Warm Brown, Graphite) seed the context picker's built-in chip colors.
        </p>
        <div class="palette-row palette-header">
          <span></span>
          <span>Id</span>
          <span>Label</span>
          <span>Hex</span>
          <span></span>
        </div>
        {#each draft.palette as swatch, i (swatch.id + ":" + i)}
          <div class="palette-row">
            <span class="palette-swatch-dot" style="background: {swatch.hex}"></span>
            <input
              type="text"
              class="palette-id-input"
              value={swatch.id}
              pattern="^[a-z0-9][a-z0-9-]*$"
              title="Lowercase letters, digits, dashes"
              on:input={(e) => paletteSetSwatch(i, { id: (e.currentTarget as HTMLInputElement).value })}
            />
            <input
              type="text"
              class="palette-label-input"
              value={swatch.label}
              on:input={(e) => paletteSetSwatch(i, { label: (e.currentTarget as HTMLInputElement).value })}
            />
            <input
              type="color"
              class="palette-color-input"
              value={swatch.hex}
              on:input={(e) => paletteSetSwatch(i, { hex: (e.currentTarget as HTMLInputElement).value })}
            />
            <span class="palette-row-actions">
              <button
                type="button"
                class="palette-row-btn"
                title="Move up"
                disabled={i === 0}
                on:click={() => paletteMoveSwatch(i, i - 1)}
              >▲</button>
              <button
                type="button"
                class="palette-row-btn"
                title="Move down"
                disabled={i === draft.palette.length - 1}
                on:click={() => paletteMoveSwatch(i, i + 1)}
              >▼</button>
              <button
                type="button"
                class="palette-row-btn palette-row-delete"
                title="Delete swatch"
                aria-label="Delete swatch"
                on:click={() => paletteRemoveSwatch(i)}
              >×</button>
            </span>
          </div>
        {/each}
        <div class="palette-add-row">
          <button type="button" title="Add color" aria-label="Add color" on:click={paletteAddSwatch}>+</button>
        </div>
      </section>

      {#snippet actions()}
        <button type="button" on:click={onCancel}>Cancel</button>
        <button class="primary" type="button" on:click={onSave}>Save</button>
      {/snippet}
  </Modal>
{/if}

<style>
  .palette-editor {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin: 12px 0 4px;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
  }

  .palette-editor h3 {
    margin: 0;
    font-size: var(--fs-md);
    font-weight: 600;
  }

  .palette-editor p.muted {
    margin: 0 0 8px;
    font-size: var(--fs-sm);
  }

  .palette-row {
    display: grid;
    grid-template-columns: 22px 1fr 1.5fr 44px auto;
    gap: 8px;
    align-items: center;
    font-size: var(--fs-sm);
  }

  .palette-row.palette-header {
    font-size: var(--fs-xs);
    color: var(--text-3);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    padding: 0 2px 4px;
    border-bottom: 1px solid var(--divider);
    margin-bottom: 4px;
  }

  .palette-swatch-dot {
    display: inline-block;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: 1px solid rgba(0, 0, 0, 0.18);
  }

  .palette-id-input,
  .palette-label-input {
    font-size: var(--fs-sm);
    padding: 3px 6px;
    border: 1px solid var(--border);
    border-radius: 4px;
    min-width: 0;
  }

  .palette-id-input {
    font-family: var(--mono);
  }

  .palette-color-input {
    width: 44px;
    height: 26px;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
  }

  .palette-row-actions {
    display: inline-flex;
    gap: 2px;
  }

  .palette-row-btn {
    appearance: none;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: var(--fs-xs);
    color: var(--text-2);
    cursor: pointer;
    line-height: 1;
  }

  .palette-row-btn:hover:not(:disabled) {
    background: var(--panel);
    border-color: var(--border);
  }

  .palette-row-btn:disabled {
    opacity: 0.35;
    cursor: default;
  }

  .palette-row-delete:hover:not(:disabled) {
    color: var(--danger);
    background: var(--danger-soft);
    border-color: var(--danger-border);
  }

  .palette-add-row {
    margin-top: 8px;
  }

  .palette-add-row button {
    font-size: var(--fs-sm);
    padding: 4px 10px;
    border: 1px dashed var(--border-strong);
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
    color: var(--text-2);
  }

  .palette-add-row button:hover {
    border-style: solid;
    background: var(--panel);
  }

  /* The frame's `.machine-settings-modal` class lives on Modal's own <div>
     (child scope), so it must be :global; the code/label/input it anchors are
     this dialog's slotted content and stay scoped. Sizing is handled by the
     --modal-* custom props set via frameStyle, so there's no bare frame rule. */
  :global(.machine-settings-modal) code {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    background: var(--inset);
    padding: 1px 5px;
    border-radius: 3px;
  }

  :global(.machine-settings-modal) label {
    display: grid;
    gap: 4px;
    font-size: var(--fs-md);
  }

  :global(.machine-settings-modal) input {
    font-size: var(--fs-md);
    padding: 6px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
  }
</style>
