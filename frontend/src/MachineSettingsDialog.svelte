<script lang="ts">
  // Machine-settings dialog. Holds the editing UI for the user's
  // machine config: default folder, provider API keys, Ollama host,
  // and the color palette editor. The parent loads / persists the
  // draft; this component owns only the local mutations on the draft
  // it's been handed.
  import type { MachineSettingsDraft, MachineSettingsView, Swatch } from "./types";
  import Modal from "./Modal.svelte";

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
        Default projects folder
        <div class="path-picker-row">
          <input type="text" bind:value={draft.default_projects_folder} placeholder="C:\path\to\writing" />
          <button
            type="button"
            disabled={!draft.default_projects_folder}
            on:click={() => draft && (draft.default_projects_folder = "")}
          >Clear</button>
        </div>
        <small class="muted">Where new projects get created by default. Leave empty to require an explicit folder each time. The project switcher reads recent projects from this config too.</small>
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
                on:click={() => paletteRemoveSwatch(i)}
              >×</button>
            </span>
          </div>
        {/each}
        <div class="palette-add-row">
          <button type="button" on:click={paletteAddSwatch}>+ Add color</button>
        </div>
      </section>

      {#snippet actions()}
        <button type="button" on:click={onCancel}>Cancel</button>
        <button class="primary" type="button" on:click={onSave}>Save</button>
      {/snippet}
  </Modal>
{/if}
