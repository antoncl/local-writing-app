<script lang="ts">
  // The no-project state (#417 slice 6, #2558). Before a project opens there is no
  // tiled Workspace — its layout is keyed per project — so the guide viewer, a
  // workspace region once a project is open, renders here instead. GuideView is
  // bundled data and needs no project, so a new user can read "Getting started"
  // before they have worked out how to create one.
  import GuideView from "@/components/panes/GuideView.svelte";
  import { guideTarget } from "@/lib/stores/guideTarget.svelte";

  let { guideOpen = $bindable(false) }: { guideOpen?: boolean } = $props();

  function openGettingStarted() {
    guideTarget.request("getting-started");
    guideOpen = true;
  }
</script>

<div class="welcome" data-testid="no-project">
  <div class="welcome-head">
    <p class="muted welcome-hint">
      No project open. Pick one from the switcher above — recents, browse, or create new.
    </p>
    {#if guideOpen}
      <button type="button" class="welcome-close" title="Close guides" aria-label="Close guides" onclick={() => (guideOpen = false)}>×</button>
    {:else}
      <button type="button" class="welcome-guide-link" onclick={openGettingStarted}>Read the Getting started guide</button>
    {/if}
  </div>
  {#if guideOpen}
    <div class="welcome-guide">
      <GuideView />
    </div>
  {/if}
</div>

<style>
  .welcome {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: var(--sp-5);
    gap: var(--sp-3);
    overflow: auto;
  }
  /* One column with the reading frame below, so the × lines up with its edge. */
  .welcome-head {
    width: min(880px, 100%);
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--sp-2) var(--sp-3);
  }
  .welcome-hint {
    margin: var(--sp-1) 0;
    font-size: var(--fs-md);
  }
  /* An `md` outline button (design-language §4) — the global button default is larger. */
  .welcome-guide-link {
    font-size: var(--fs-md);
    padding: var(--sp-1) var(--sp-3);
  }
  .welcome-close {
    margin-left: auto;
    border: none;
    background: transparent;
  }
  /* The reading surface: GuideView fills this frame (its root is height: 100%). */
  .welcome-guide {
    flex: 1 1 auto;
    min-height: 0;
    width: min(880px, 100%);
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    overflow: hidden;
  }
</style>
