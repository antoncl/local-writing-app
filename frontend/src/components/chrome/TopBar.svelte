<script lang="ts">
  import type { ProjectChainLayer, ProjectChild, RecentProject } from "@/lib/types";
  import type { ThemePreference } from "@/lib/utils/theme";

  import ProjectBreadcrumb from "./ProjectBreadcrumb.svelte";

  // Null when no project is open — switcher shows "Open a project…".
  export let currentTitle: string | null;
  // Resolved hex for the open project's color, or null if no color set.
  // Rendered as a small dot before the title so the user can tell which
  // project they're in at a glance (especially when nesting lands).
  export let currentProjectColor: string | null = null;
  export let recentProjects: RecentProject[] = [];
  // The open project's place in the hierarchy (#311). Ancestors render as the
  // breadcrumb to the left; children ride in the switcher menu, because both
  // directions are the same gesture — open a different project — and because
  // the Project pane that also lists the children is not guaranteed to be on
  // screen (#417). Ascent is chrome, so descent has to be too.
  // The resolved chain (#432), passed straight through to the breadcrumb.
  export let chain: ProjectChainLayer[] = [];
  export let childProjects: ProjectChild[] = [];
  export let onOpenProjectPath: (path: string) => void = () => {};
  // Reveal the inheritance declaration editor (#426) for the empty-chain note
  // (#427). Not the same gesture as the Project action button below: that one
  // opens the project NODE in an editor tab, this one brings the Project pane
  // — which is where the declaration list lives — back on screen.
  export let onOpenInheritance: () => void = () => {};
  // Whether that editor would have anything to offer (#427) — the ancestor
  // enumeration is empty for a project outside the machine root.
  export let canDeclareInheritance: boolean = false;
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

  // Layout presets (#155). The built-in preset the current arrangement matches
  // (or null for a custom layout), the user's saved preset names, and the
  // callbacks that apply / save / delete / reset. Layout is a project-scoped
  // concern, so the button is disabled with no project open.
  export let activePreset: string | null = null;
  export let userPresets: string[] = [];
  export let onApplyPreset: (name: string) => void = () => {};
  export let onApplyUserPreset: (name: string) => void = () => {};
  export let onSavePreset: (name: string) => void = () => {};
  export let onDeleteUserPreset: (name: string) => void = () => {};
  export let onResetLayout: () => void = () => {};

  const BUILT_IN_PRESETS: { key: string; label: string }[] = [
    { key: "writing", label: "Writing" },
    { key: "schema", label: "Schema & types" },
    { key: "research", label: "Research" },
  ];

  let layoutOpen = false;
  let layoutButton: HTMLButtonElement | null = null;
  let showSaveField = false;
  let saveName = "";

  function resetSaveField() {
    showSaveField = false;
    saveName = "";
  }

  function toggleLayout() {
    layoutOpen = !layoutOpen;
    if (!layoutOpen) resetSaveField();
  }

  function closeLayout() {
    layoutOpen = false;
    resetSaveField();
  }

  function applyBuiltIn(key: string) {
    closeLayout();
    onApplyPreset(key);
  }

  function applyUser(name: string) {
    closeLayout();
    onApplyUserPreset(name);
  }

  function resetLayout() {
    closeLayout();
    onResetLayout();
  }

  function commitSave() {
    const name = saveName.trim();
    if (!name) return;
    onSavePreset(name);
    closeLayout();
  }

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

  function handleOpenProjectPath(path: string) {
    closeSwitcher();
    // Opening a project rebuilds the chain, so the control that was activated
    // may not exist afterwards — a crumb for a level the new project does not
    // declare simply goes away, dropping keyboard focus to <body> and sending
    // the next Tab back to the top of the document. The switcher button is the
    // one anchor here that survives every scope change, which is why the
    // Escape path already restores to it.
    switcherButton?.focus();
    onOpenProjectPath(path);
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
    if (event.key !== "Escape") return;
    if (switcherOpen) {
      switcherOpen = false;
      switcherButton?.focus();
    }
    if (layoutOpen) {
      closeLayout();
      layoutButton?.focus();
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

  <ProjectBreadcrumb
    {chain}
    canDeclare={canDeclareInheritance}
    onOpen={handleOpenProjectPath}
    onSetUpInheritance={onOpenInheritance}
  />

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
        {#if childProjects.length > 0}
          <div class="switcher-section-label">Contains</div>
          {#each childProjects as child (child.path)}
            <button
              type="button"
              class="switcher-item child-item"
              role="menuitem"
              on:click={() => handleOpenProjectPath(child.path)}
            >
              <span class="child-title">{child.title}</span>
              {#if child.name !== child.title}
                <span class="child-folder">{child.name}</span>
              {/if}
            </button>
          {/each}
          <div class="switcher-divider" role="separator"></div>
        {/if}
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

    <div class="layout-wrap">
      <button
        bind:this={layoutButton}
        type="button"
        class="action-button"
        class:active={layoutOpen}
        disabled={!projectOpen}
        aria-haspopup="menu"
        aria-expanded={layoutOpen}
        on:click={toggleLayout}
      >Layout <span class="chevron" aria-hidden="true">▾</span></button>

      {#if layoutOpen}
        <!-- click-outside dismiss -->
        <div class="switcher-overlay" role="presentation" on:click={closeLayout}></div>

        <div class="layout-menu" role="menu" aria-label="Layout presets">
          <div class="switcher-section-label">Presets</div>
          {#each BUILT_IN_PRESETS as preset (preset.key)}
            <button
              type="button"
              class="switcher-item preset-item"
              role="menuitemradio"
              aria-checked={activePreset === preset.key}
              on:click={() => applyBuiltIn(preset.key)}
            >
              <span class="preset-check" aria-hidden="true">{activePreset === preset.key ? "✓" : ""}</span>
              {preset.label}
            </button>
          {/each}

          {#if userPresets.length > 0}
            <div class="switcher-divider" role="separator"></div>
            <div class="switcher-section-label">Saved</div>
            {#each userPresets as name (name)}
              <div class="preset-user-row">
                <button type="button" class="switcher-item preset-item preset-user" role="menuitem" on:click={() => applyUser(name)}>
                  <span class="preset-check" aria-hidden="true"></span>
                  <span class="preset-user-name">{name}</span>
                </button>
                <button
                  type="button"
                  class="preset-delete"
                  title="Delete {name}"
                  aria-label="Delete preset {name}"
                  on:click={() => onDeleteUserPreset(name)}
                >×</button>
              </div>
            {/each}
          {/if}

          <div class="switcher-divider" role="separator"></div>
          {#if showSaveField}
            <form class="preset-save" on:submit|preventDefault={commitSave}>
              <!-- svelte-ignore a11y_autofocus -->
              <input
                type="text"
                bind:value={saveName}
                placeholder="Preset name"
                aria-label="New preset name"
                autofocus
              />
              <button type="submit" disabled={!saveName.trim()}>Save</button>
            </form>
          {:else}
            <button type="button" class="switcher-item" role="menuitem" on:click={() => (showSaveField = true)}>
              <span class="switcher-icon" aria-hidden="true">+</span>
              Save current as…
            </button>
          {/if}
          <button type="button" class="switcher-item" role="menuitem" on:click={resetLayout}>
            Reset to default
          </button>
        </div>
      {/if}
    </div>

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
    /* Fixed, so it never absorbs the breadcrumb's pressure. Measured before
       this: four crumbs at 1280px wrapped "Local Writer" onto two lines inside
       a 40px bar — the bar reported no overflow precisely *because* the
       wordmark and the action cluster silently wrapped instead (#311). */
    flex: none;
    white-space: nowrap;
  }

  .top-bar .switcher-wrap {
    position: relative;
    /* The floor lives on the flex item, not just on the button inside it.
       With it only on the button, this wrapper's automatic minimum did not
       resolve under pressure from the breadcrumb: the chain bottomed out at 0
       while the switcher held its full 360px, and the bar overflowed to 905px
       in a 760px window — carrying the settings button off-screen. Stated
       explicitly, the switcher gives 360 -> 200 the way it did before #311. */
    min-width: 200px;
    max-width: 360px;
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
    /* Fills the wrapper, which now carries the 200-360 range. The earlier
       attempt to make the floor conditional — `min(200px, 100%)` — did not
       soften it, it deleted it: the percentage resolved against a shrink-to-fit
       parent, i.e. as `auto`. Measured at 144px instead of 200px at 1280px
       wide, for every project with no declared chain. */
    width: 100%;
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
    /* `children` is uncapped, unlike `recentProjects` which the backend caps at
       RECENT_PROJECTS_MAX. A shelf with many book folders grew this menu past
       the bottom of the window and took "Open folder…" / "New project…" with
       it — the app's only entry affordances — with nothing to scroll, since the
       page behind is a separate scroll container. */
    max-height: calc(100vh - 60px);
    overflow-y: auto;
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

  .top-bar .child-item {
    justify-content: space-between;
  }

  .top-bar .child-title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    /* Without these the ellipsis never fires: `min-width: auto` on a flex item
       resolves to its intrinsic content width, so a long child title widens
       the row instead of being clipped by it. Same pair `.switcher-label`
       already uses a few rules up. */
    flex: 1;
    min-width: 0;
  }

  .top-bar .child-folder {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-3);
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
    /* Same reason as the wordmark: these are fixed chrome, and letting them
       shrink made them wrap to 44px inside a 40px bar rather than pushing back
       on the thing that actually has a scroll fallback. */
    flex: none;
    white-space: nowrap;
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

  .top-bar .layout-wrap {
    position: relative;
  }

  .top-bar .action-button.active {
    background: var(--panel);
    border-color: var(--border);
  }

  .top-bar .action-button .chevron {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }

  .top-bar .layout-menu {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    z-index: 101;
    min-width: 220px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    box-shadow: var(--elev-2);
    padding: 6px;
    display: grid;
    gap: 1px;
  }

  .top-bar .preset-item {
    gap: 6px;
  }

  .top-bar .preset-check {
    width: 14px;
    flex: none;
    text-align: center;
    color: var(--accent-emphasis);
    font-size: var(--fs-sm);
  }

  .top-bar .preset-user-row {
    display: flex;
    align-items: center;
  }

  .top-bar .preset-user {
    flex: 1;
    min-width: 0;
  }

  .top-bar .preset-user-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .top-bar .preset-delete {
    flex: none;
    width: 24px;
    height: 24px;
    border: 1px solid transparent;
    border-radius: 4px;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-md);
    line-height: 1;
    cursor: pointer;
  }

  .top-bar .preset-delete:hover {
    background: var(--danger-soft);
    color: var(--danger);
  }

  .top-bar .preset-save {
    display: flex;
    gap: 6px;
    padding: 4px;
  }

  .top-bar .preset-save input {
    flex: 1;
    min-width: 0;
    padding: 4px 8px;
    border: 1px solid var(--divider);
    border-radius: 4px;
    background: var(--inset);
    color: var(--text);
    font-size: var(--fs-md);
  }

  .top-bar .preset-save button {
    flex: none;
    padding: 4px 10px;
    border: 1px solid var(--divider);
    border-radius: 4px;
    background: var(--surface);
    color: var(--text);
    font-size: var(--fs-md);
    cursor: pointer;
  }

  .top-bar .preset-save button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
