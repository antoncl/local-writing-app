<script lang="ts">
  import type { RecentProject } from "./types";

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
  export let onOpenAssistants: () => void = () => {};
  export let onOpenSettings: () => void = () => {};
  // Detail Types is project-scoped — disabled when no project is open.
  export let onOpenDetailTypes: () => void = () => {};
  export let onOpenProjectNode: () => void = () => {};
  export let projectOpen: boolean = false;

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
    <button type="button" class="action-button" on:click={onOpenAssistants}>Assistants</button>
    <button type="button" class="action-button icon-button" aria-label="Settings" title="Settings" on:click={onOpenSettings}>
      <span aria-hidden="true">⚙</span>
    </button>
  </div>
</header>
