<script lang="ts">
  // The app's house boolean control: a track + sliding knob (role="switch"),
  // the same idiom FieldValueEditor renders for boolean field values. Extracted
  // as a shared widget so on/off booleans read consistently instead of a raw
  // checkbox. Presentation-only `disabled` blocks the click without changing
  // state. (#1068 — FieldValueEditor's own hand-rolled copy can migrate here;
  // tracked separately so its tri-state "unset" path isn't reworked in passing.)
  interface Props {
    checked: boolean;
    ariaLabel: string;
    disabled?: boolean;
    onChange: (next: boolean) => void;
  }
  let { checked, ariaLabel, disabled = false, onChange }: Props = $props();
</script>

<button
  type="button"
  role="switch"
  class="toggle-switch"
  class:on={checked}
  aria-checked={checked}
  aria-label={ariaLabel}
  {disabled}
  onclick={() => onChange(!checked)}
>
  <span class="toggle-switch-knob"></span>
</button>

<style>
  .toggle-switch {
    flex: none;
    width: 34px;
    height: 20px;
    padding: 0;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--inset);
    cursor: pointer;
    position: relative;
    transition:
      background-color 120ms ease,
      border-color 120ms ease;
  }
  .toggle-switch:disabled {
    cursor: default;
    opacity: 0.6;
  }
  .toggle-switch-knob {
    position: absolute;
    top: 1px;
    left: 1px;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--surface);
    box-shadow: 0 1px 2px var(--shadow-pane);
    transition: transform 120ms ease;
  }
  .toggle-switch.on {
    background: var(--accent);
    border-color: var(--accent);
  }
  .toggle-switch.on .toggle-switch-knob {
    transform: translateX(14px);
  }
</style>
