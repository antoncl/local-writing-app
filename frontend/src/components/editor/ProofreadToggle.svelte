<script lang="ts">
  // Proofreading (ADR-0102 §1): the lens switch, in a scene's footer. Quiet
  // when off; tinted while on; says so while the engine loads the first time.
  import { proofreading } from "@/lib/stores/proofreading.svelte";

  const label = $derived(
    proofreading.status === "loading" && proofreading.on ? "Proofreading…" : "Proofread",
  );
  const title = $derived(
    proofreading.status === "error"
      ? `Proofreading couldn't start: ${proofreading.error ?? "unknown error"}`
      : proofreading.on
        ? "Stop proofreading"
        : "Proofread — underline spelling and grammar for a revision pass",
  );
</script>

<button
  type="button"
  class="proofread-toggle"
  class:active={proofreading.on}
  class:failed={proofreading.status === "error"}
  aria-pressed={proofreading.on}
  {title}
  data-testid="proofread-toggle"
  onclick={() => proofreading.toggle()}
>
  {label}
</button>

<style>
  .proofread-toggle {
    padding: 2px 8px;
    border: none;
    border-radius: var(--r-sm);
    background: transparent;
    color: var(--text-3);
    font: inherit;
    cursor: pointer;
  }
  .proofread-toggle:hover,
  .proofread-toggle:focus-visible {
    color: var(--text);
  }
  .proofread-toggle.active {
    background: var(--accent-soft);
    color: var(--accent-strong);
  }
  .proofread-toggle.failed {
    color: var(--danger);
  }
</style>
