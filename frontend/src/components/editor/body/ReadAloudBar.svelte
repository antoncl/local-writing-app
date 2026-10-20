<!--
  ReadAloudBar (#2570) - the player of a read-aloud: where it is, pause / stop,
  flag the sentence being read, speed and voice. NodeEditor's footer mounts it
  as a row of the editor pane while this document is being read, OUTSIDE the
  scroll frame, so it never covers text.

  Pure presentation over the readAloud controller. mousedown preventDefault
  keeps the editor focused, so the reading keys (Alt+Shift+P pause, Alt+Shift+F
  flag, Esc stop) keep working after a click here.
-->
<script lang="ts">
  import { onDestroy } from "svelte";
  import { readAloud, READ_ALOUD_RATES } from "@/lib/stores/readAloud.svelte";

  const FLAGGED_MS = 1500;
  const keepFocus = (e: MouseEvent) => e.preventDefault();

  let justFlagged = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let seenFlagAt = readAloud.lastFlagAt;
  $effect(() => {
    const at = readAloud.lastFlagAt;
    if (at === seenFlagAt) return;
    seenFlagAt = at;
    justFlagged = true;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => (justFlagged = false), FLAGGED_MS);
  });
  onDestroy(() => timer && clearTimeout(timer));

  const paused = $derived(readAloud.status === "paused");
  const alreadyFlagged = $derived(readAloud.flaggedIndexes.includes(readAloud.index));
  const flagTitle = $derived(
    !readAloud.canFlag
      ? "Flags are scene TODOs — open a scene to flag"
      : alreadyFlagged ? "This sentence is flagged" : "Flag this sentence as a TODO (Alt+Shift+F)",
  );
</script>

<div class="read-aloud-bar" data-testid="read-aloud-bar" role="toolbar" aria-label="Read aloud">
  <span class="rab-status" data-testid="read-aloud-status">
    {paused ? "Paused" : "Reading aloud"} · sentence {readAloud.index + 1} of {readAloud.total}
  </span>
  <span class="rab-group">
    <button type="button" class="rab-btn" data-testid="read-aloud-toggle" title={paused ? "Resume (Alt+Shift+P)" : "Pause (Alt+Shift+P)"} onmousedown={keepFocus} onclick={() => readAloud.togglePause()}>
      {paused ? "Resume" : "Pause"} <kbd>Alt+Shift+P</kbd>
    </button>
    <button type="button" class="rab-btn" data-testid="read-aloud-stop" title="Stop reading (Esc)" onmousedown={keepFocus} onclick={() => readAloud.stop()}>
      Stop <kbd>Esc</kbd>
    </button>
    <button type="button" class="rab-btn" data-testid="read-aloud-flag" title={flagTitle} disabled={!readAloud.canFlag || alreadyFlagged} onmousedown={keepFocus} onclick={() => readAloud.flag()}>
      Flag <kbd>Alt+Shift+F</kbd>
    </button>
    {#if justFlagged}<span class="rab-flagged" data-testid="read-aloud-flagged">Flagged</span>{/if}
  </span>
  <span class="rab-group">
    <select class="rab-select" data-testid="read-aloud-rate" aria-label="Reading speed" value={String(readAloud.rate)} onchange={(e) => readAloud.setRate(Number(e.currentTarget.value))}>
      {#each READ_ALOUD_RATES as rate (rate)}<option value={String(rate)}>{rate}×</option>{/each}
    </select>
    <select class="rab-select" data-testid="read-aloud-voice" aria-label="Voice" value={readAloud.voiceURI} onchange={(e) => readAloud.setVoice(e.currentTarget.value)}>
      <option value="">System default</option>
      {#each readAloud.voices as voice (voice.voiceURI)}<option value={voice.voiceURI}>{voice.name} ({voice.lang})</option>{/each}
    </select>
  </span>
</div>

<style>
  .read-aloud-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 2px 4px;
    padding: 6px 12px;
    background: var(--surface);
    border-top: 1px solid var(--divider);
    font-size: var(--fs-sm);
    color: var(--text-2);
    cursor: default;
    user-select: none;
  }

  .rab-group {
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }

  .rab-status {
    flex: none;
    font-weight: 500;
    color: var(--text);
    padding-right: 4px;
  }

  .rab-btn {
    flex: none;
    background: transparent;
    border: none;
    color: var(--text-2);
    padding: 4px 8px;
    font-size: var(--fs-sm);
    line-height: 1;
    border-radius: 4px;
    cursor: pointer;
  }

  .rab-btn kbd {
    font: inherit;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }

  .rab-btn:hover:not(:disabled) {
    background: var(--inset);
    color: var(--text);
  }

  .rab-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .rab-flagged {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }

  .rab-select {
    flex: none;
    max-width: 180px;
    background: var(--inset);
    border: none;
    color: var(--text-2);
    padding: 3px 6px;
    font-size: var(--fs-sm);
    border-radius: 4px;
  }
</style>
