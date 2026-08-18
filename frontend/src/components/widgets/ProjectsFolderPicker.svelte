<script lang="ts">
  import DirectoryPickerModal from "@/components/dialogs/DirectoryPickerModal.svelte";

  let {
    // The canonical projects-folder editor (#643 / ADR-0047 slice 4). One control,
    // mounted by Settings → Storage (the persistent home) and the New-project
    // wizard's first-run root step. Both write `default_projects_folder`; this
    // owns the row (input + Browse + optional Clear) and its own directory picker.
    value,
    // The host owns the value. Called on every keystroke, on a Browse selection,
    // and on Clear — the host decides where the string lands (a settings draft,
    // the wizard's root draft).
    onChange,
    // Settings offers Clear (emptying the root is a real, warned-about choice);
    // the wizard does not — first-run must set a root to continue.
    showClear = false,
    // Dialog heading. The two homes historically phrased it differently, so it is
    // a prop rather than baked in.
    pickerTitle = "Projects Folder",
    // Where Browse opens when the field is empty (the wizard's first-run start
    // folder). Settings leaves it empty and opens at the current value.
    startPath = "",
  }: {
    value: string;
    onChange: (value: string) => void;
    showClear?: boolean;
    pickerTitle?: string;
    startPath?: string;
  } = $props();

  let pickerOpen = $state(false);
</script>

<div class="path-picker-row" class:with-clear={showClear}>
  <input
    type="text"
    value={value}
    placeholder="C:\path\to\writing"
    oninput={(event) => onChange(event.currentTarget.value)}
  />
  <button type="button" onclick={() => (pickerOpen = true)}>Browse…</button>
  {#if showClear}
    <button type="button" disabled={!value} onclick={() => onChange("")}>Clear</button>
  {/if}
</div>

<DirectoryPickerModal
  open={pickerOpen}
  initialPath={value || startPath}
  title={pickerTitle}
  selectLabel="Use This Folder"
  onClose={() => (pickerOpen = false)}
  onSelect={(path) => {
    onChange(path);
    pickerOpen = false;
  }}
/>

<style>
  /* The base `.path-picker-row` (global, styles.css) is a two-column grid
     (input + one button). With Clear the row grows a third column. */
  .path-picker-row.with-clear {
    grid-template-columns: minmax(0, 1fr) auto auto;
  }
</style>
