<script lang="ts">
  import type { RecentProject } from "@/lib/types";
  import type { ThemePreference } from "@/lib/utils/theme";

  // Null when no project is open — switcher shows "Open a project…".
  export let currentTitle: string | null;
  // Resolved hex for the open project's color, or null if no color set.
  // Rendered as a small dot before the title so the user can tell which
  // project they're in at a glance (especially when nesting lands).
  export let currentProjectColor: string | null = null;
  export let recentProjects: RecentProject[] = [];
  // Event hooks. The parent owns all side effects; this component is
  // purely presentational + dropdown state.
  export let onSelectRecent: (path: string) => void = () => {};
  export let onOpenFolder: () => void = () => {};
  export let onNewProject: () => void = () => {};
  // Assistants (like Detail Types / Project) is project-scoped — its editor
  // lives in the workspace shell, so the button is disabled with no project open.
  export let onOpenAssistants: () => void = () => {};
  export let onOpenSettings: () => void = () => {};
  // Detail Types is project-scoped — disabled when no project is open.
  export let onOpenDetailTypes: () => void = () => {};
  export let onOpenProjectNode: () => void = () => {};
  export let projectOpen: boolean = false;
  // Theme toggle. Current preference + a callback that cycles to the
  // next one. The button shows an icon for the current state and a
  // tooltip naming what the next click will switch to.
  export let themePref: ThemePreference = "system";
  export let onCycleTheme: () => void = () => {};

  const THEME_GLYPH: Record<ThemePreference, string> = {
    system: "◐",
    light: "☀",
    dark: "☾",
  };
  const THEME_NEXT_LABEL: Record<ThemePreference, string> = {
    system: "Switch to light theme",
    light: "Switch to dark theme",
    dark: "Follow system theme",
  };
  $: themeGlyph = THEME_GLYPH[themePref];
  $: themeNextLabel = THEME_NEXT_LABEL[themePref];

  let switcherOpen = false;
  let switcherButton: HTMLButtonElement | null = null;

  function toggleSwitcher() {
    switcherOpen = !switcherOpen;
  }

  function closeSwitcher() {
    switcherOpen = false;
  }

  function handleSelectRecent(path: string) {
    closeSwitcher();
    onSelectRecent(path);
  }

  function handleOpenFolder() {
    closeSwitcher();
    onOpenFolder();
  }

  function handleNewProject() {
    closeSwitcher();
    onNewProject();
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === "Escape" && switcherOpen) {
      switcherOpen = false;
      switcherButton?.focus();
    }
  }

  function formatRelativeTime(iso: string): string {
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "";
    const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
    if (seconds < 60) return "just now";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.round(hours / 24);
    if (days < 30) return `${days}d ago`;
    const months = Math.round(days / 30);
    if (months < 12) return `${months}mo ago`;
    return `${Math.round(months / 12)}y ago`;
  }

  function shortenPath(path: string): string {
    // Show the last two segments to keep the dropdown narrow but
    // disambiguating: ".../parent/name".
    const segments = path.split(/[\\/]/).filter(Boolean);
    if (segments.length <= 2) return path;
    return `…/${segments.slice(-2).join("/")}`;
  }
</script>

<svelte:window on:keydown={handleKeydown} />

<header class="top-bar">
  <span class="wordmark">Local Writer</span>

  <div class="switcher-wrap">
    <button
      bind:this={switcherButton}
      type="button"
      class="switcher-button"
      class:active={switcherOpen}
      aria-haspopup="menu"
      aria-expanded={switcherOpen}
      on:click={toggleSwitcher}
    >
      <span class="chevron" aria-hidden="true">▾</span>
      {#if currentProjectColor}
        <span class="project-color-dot" aria-hidden="true" style={`background: ${currentProjectColor}`}></span>
      {/if}
      <span class="switcher-label">{currentTitle ?? "Open a project…"}</span>
    </button>

    {#if switcherOpen}
      <!-- click-outside dismiss -->
      <div
        class="switcher-overlay"
        role="presentation"
        on:click={closeSwitcher}
      ></div>

      <div class="switcher-menu" role="menu" aria-label="Project switcher">
        {#if recentProjects.length > 0}
          <div class="switcher-section-label">Recent</div>
          {#each recentProjects as recent (recent.path)}
            <button
              type="button"
              class="switcher-item recent-item"
              role="menuitem"
              on:click={() => handleSelectRecent(recent.path)}
            >
              <span class="recent-title">{recent.title}</span>
              <span class="recent-meta">
                <span class="recent-path" title={recent.path}>{shortenPath(recent.path)}</span>
                <span class="recent-time">{formatRelativeTime(recent.opened_at)}</span>
              </span>
            </button>
          {/each}
          <div class="switcher-divider" role="separator"></div>
        {/if}
        <button type="button" class="switcher-item" role="menuitem" on:click={handleOpenFolder}>
          <span class="switcher-icon" aria-hidden="true">📁</span>
          Open folder…
        </button>
        <button type="button" class="switcher-item" role="menuitem" on:click={handleNewProject}>
          <span class="switcher-icon" aria-hidden="true">✨</span>
          New project…
        </button>
      </div>
    {/if}
  </div>

  <div class="actions">
    <button type="button" class="action-button" disabled={!projectOpen} on:click={onOpenProjectNode}>Project</button>
    <button type="button" class="action-button" disabled={!projectOpen} on:click={onOpenDetailTypes}>Detail Types</button>
    <button type="button" class="action-button" disabled={!projectOpen} on:click={onOpenAssistants}>Assistants</button>
    <button
      type="button"
      class="action-button icon-button"
      aria-label={themeNextLabel}
      title={themeNextLabel}
      on:click={onCycleTheme}
    >
      <span aria-hidden="true">{themeGlyph}</span>
    </button>
    <button type="button" class="action-button icon-button" aria-label="Settings" title="Settings" on:click={onOpenSettings}>
      <span aria-hidden="true">⚙</span>
    </button>
  </div>
</header>

<style>
  .top-bar {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 40px;
    z-index: 100;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 0 16px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    box-shadow: var(--elev-1);
  }

  .top-bar .wordmark {
    font-weight: 600;
    font-size: var(--fs-md);
    color: var(--text);
    letter-spacing: 0.02em;
    user-select: none;
  }

  .top-bar .switcher-wrap {
    position: relative;
  }

  .top-bar .switcher-button {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border: 1px solid var(--divider);
    background: var(--inset);
    color: var(--text);
    font-size: var(--fs-md);
    border-radius: 6px;
    cursor: pointer;
    min-width: 200px;
    max-width: 360px;
  }

  .top-bar .switcher-button:hover,
  .top-bar .switcher-button.active {
    background: var(--panel);
    border-color: var(--border);
  }

  .top-bar .switcher-button .chevron {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }

  .top-bar .switcher-button .switcher-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    text-align: left;
  }

  .top-bar .switcher-button .project-color-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    flex: none;
    border-radius: 50%;
    border: 1px solid rgba(0, 0, 0, 0.18);
  }

  /* `.entry-type-dot` removed — Phase 4 used it on lore rows, but per
     [[decisions-ui-widget-taxonomy]] whole-row color belongs on a Stripe
     (the NodeRow `.has-status-stripe` band), not an inline Dot. The Dot
     pattern is reserved for label clusters (e.g. .project-color-dot in the
     switcher). */

  .top-bar .switcher-overlay {
    position: fixed;
    inset: 0;
    z-index: 99;
  }

  .top-bar .switcher-menu {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    z-index: 101;
    min-width: 320px;
    max-width: 480px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: var(--elev-2);
    padding: 6px;
    display: grid;
    gap: 1px;
  }

  .top-bar .switcher-section-label {
    font-size: var(--fs-xs);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-3);
    padding: 6px 10px 2px;
    font-weight: 600;
  }

  .top-bar .switcher-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    color: var(--text);
    font-size: var(--fs-md);
    text-align: left;
    cursor: pointer;
    width: 100%;
  }

  .top-bar .switcher-item:hover {
    background: var(--panel);
  }

  .top-bar .recent-item {
    flex-direction: column;
    align-items: stretch;
    gap: 2px;
  }

  .top-bar .recent-title {
    font-weight: 500;
    color: var(--text);
  }

  .top-bar .recent-meta {
    display: flex;
    gap: 8px;
    font-size: var(--fs-xs);
    color: var(--text-3);
    justify-content: space-between;
  }

  .top-bar .recent-path {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--mono);
  }

  .top-bar .switcher-divider {
    height: 1px;
    background: var(--divider);
    margin: 4px 0;
  }

  .top-bar .switcher-icon {
    width: 18px;
    text-align: center;
  }

  .top-bar .actions {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .top-bar .action-button {
    padding: 4px 10px;
    font-size: var(--fs-md);
    border: 1px solid var(--divider);
    background: var(--surface);
    border-radius: 6px;
    cursor: pointer;
    color: var(--text);
  }

  .top-bar .action-button:hover:not(:disabled) {
    background: var(--panel);
  }

  .top-bar .action-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .top-bar .icon-button {
    padding: 4px 8px;
    font-size: var(--fs-xl);
    line-height: 1;
  }
</style>
