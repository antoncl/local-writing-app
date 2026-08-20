<!--
  ProseSelectionToolbar — the single floating menu shown over a prose selection
  (and, in a table, over the caret) in ProseBodyView (#1223).

  Purely a view: the host owns the menu state (open/position/placement), builds
  the action list (Bold/Italic/Strike + the AI "Revise" menu + "Style" block
  menu + "To-do", and a "Table" menu when the caret is in a table), and runs the
  commands (wrapping each in focusAndRun so the editor keeps focus). This renders
  the buttons, one-level dropdowns, and the Table menu's nested submenus, and
  calls back on activation. onmousedown handlers preventDefault so a click never
  blurs the editor. Top-level dropdowns are click-to-open (host owns openMenuId);
  submenus open on hover within an already-open dropdown (local state).
-->
<script lang="ts">
  import {
    isToolbarSeparator,
    isToolbarSubmenu,
    verticalDropFit,
    type FloatingMenuState,
    type ToolbarAction,
    type ToolbarMenuEntry,
  } from "@/lib/editor-core/selectionToolbar";

  interface Props {
    menu: FloatingMenuState;
    actions: ToolbarAction[];
    openMenuId: string | null;
    onRun: (run: () => void | Promise<void>) => void;
    onToggleMenu: (actionId: string) => void;
  }

  let { menu, actions, openMenuId, onRun, onToggleMenu }: Props = $props();

  // Which Table submenu (Row/Column/…) is open, and whether it flips to the left
  // to stay on-screen. Local because submenus open on hover, not via the host.
  let openSubmenuId: string | null = $state(null);
  let submenuFlip = $state(false);
  const SUBMENU_WIDTH = 178;

  // Dropdown open direction + height cap, measured from the trigger so a menu
  // opens toward the room and never clips off-screen (#1227) — decoupled from
  // the toolbar's own above/below placement. One top-level dropdown is open at a
  // time, so a single set of values suffices; submenus track their own.
  let dropUp = $state(false);
  let menuMaxHeight = $state(320);
  let submenuFlipUp = $state(false);
  let submenuMaxHeight = $state(320);

  // A closed (or switched) top-level dropdown collapses any open submenu.
  $effect(() => {
    void openMenuId;
    openSubmenuId = null;
  });

  // Measure when a top-level dropdown is about to OPEN (not on close/toggle-off).
  function measureDropdown(actionId: string, event: MouseEvent) {
    if (openMenuId === actionId) return; // toggling closed — nothing to place
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    const fit = verticalDropFit(rect.top, rect.bottom, window.innerHeight);
    dropUp = fit.up;
    menuMaxHeight = fit.maxHeight;
  }

  function openSubmenu(entry: ToolbarMenuEntry, event: MouseEvent) {
    openSubmenuId = entry.id;
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    submenuFlip = rect.right + SUBMENU_WIDTH > window.innerWidth;
    // A submenu opens beside its parent row, extending downward from ~its top;
    // fit it the same way so it never clips the bottom.
    const fit = verticalDropFit(rect.top, rect.top, window.innerHeight);
    submenuFlipUp = fit.up;
    submenuMaxHeight = fit.maxHeight;
  }
</script>

{#if menu.visible}
  <div class:below={menu.placement === "below"} class="selection-toolbar" style={`left: ${menu.x}px; top: ${menu.y}px;`}>
    {#if menu.wordCount > 0}
      <span class="selection-count">{menu.wordCount} {menu.wordCount === 1 ? "word" : "words"}</span>
    {/if}
    {#each actions as action (action.id)}
      {#if action.kind === "button"}
        <button
          class:danger={action.danger}
          type="button"
          onmousedown={(e) => {
            e.preventDefault();
            onRun(action.run);
          }}>{action.label}</button>
      {:else}
        <div class="toolbar-menu">
          <button
            class:open={openMenuId === action.id}
            type="button"
            onmousedown={(e) => {
              e.preventDefault();
              measureDropdown(action.id, e);
              onToggleMenu(action.id);
            }}
          >
            {action.label}
          </button>
          {#if openMenuId === action.id}
            <div class:drop-up={dropUp} class="toolbar-menu-popover" style={`max-height: ${menuMaxHeight}px`}>
              {#each action.items as entry (entry.id)}
                {#if isToolbarSeparator(entry)}
                  <div class="toolbar-menu-sep" aria-hidden="true"></div>
                {:else if isToolbarSubmenu(entry)}
                  <div class="toolbar-submenu">
                    <button
                      class="has-submenu"
                      class:open={openSubmenuId === entry.id}
                      type="button"
                      onmouseenter={(e) => openSubmenu(entry, e)}
                      onmousedown={(e) => {
                        e.preventDefault();
                        openSubmenuId = openSubmenuId === entry.id ? null : entry.id;
                        submenuFlip = e.currentTarget.getBoundingClientRect().right + SUBMENU_WIDTH > window.innerWidth;
                      }}>{entry.label}</button>
                    {#if openSubmenuId === entry.id}
                      <div class:flip={submenuFlip} class:flip-up={submenuFlipUp} class="toolbar-submenu-popover" style={`max-height: ${submenuMaxHeight}px`}>
                        {#each entry.items as sub (sub.id)}
                          {#if isToolbarSeparator(sub)}
                            <div class="toolbar-menu-sep" aria-hidden="true"></div>
                          {:else if isToolbarSubmenu(sub)}
                            <!-- one submenu level is used in practice; guard the type -->
                            <button class="has-submenu" type="button" disabled>{sub.label}</button>
                          {:else}
                            <button
                              class:danger={sub.danger}
                              type="button"
                              onmousedown={(e) => {
                                e.preventDefault();
                                onRun(sub.run);
                              }}>{sub.label}</button>
                          {/if}
                        {/each}
                      </div>
                    {/if}
                  </div>
                {:else}
                  <button
                    class:danger={entry.danger}
                    type="button"
                    onmousedown={(e) => {
                      e.preventDefault();
                      onRun(entry.run);
                    }}>{entry.label}</button>
                {/if}
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .selection-toolbar {
    position: fixed;
    z-index: 20;
    display: flex;
    align-items: center;
    max-width: min(720px, calc(100% - 24px));
    overflow: visible;
    border: 1px solid var(--toolbar-border);
    border-radius: 7px;
    background: var(--toolbar-surface);
    box-shadow: var(--toolbar-elev);
    transform: translate(-50%, calc(-100% - 8px));
  }

  .selection-toolbar.below {
    transform: translate(-50%, 0);
  }

  .selection-toolbar > button,
  .toolbar-menu > button,
  .selection-count {
    height: 34px;
    border: 0;
    border-right: 1px solid var(--toolbar-divider);
    border-radius: 0;
    background: transparent;
    color: var(--toolbar-text);
    font-size: var(--fs-md);
    font-weight: 700;
    white-space: nowrap;
  }

  .selection-toolbar > button,
  .toolbar-menu > button {
    min-width: 38px;
    padding: 0 10px;
    cursor: pointer;
  }

  /* Last top-level item loses its trailing divider (may be a button or a menu). */
  .selection-toolbar > :last-child > button,
  .selection-toolbar > button:last-child {
    border-right: 0;
  }

  .selection-toolbar > button:hover,
  .toolbar-menu > button:hover,
  .toolbar-menu > button.open {
    background: var(--toolbar-hover);
  }

  .selection-toolbar > button.danger {
    color: var(--toolbar-danger-text);
  }

  .selection-count {
    display: inline-flex;
    align-items: center;
    padding: 0 12px;
    color: var(--toolbar-text-muted);
  }

  .toolbar-menu {
    position: relative;
    display: inline-flex;
  }

  .toolbar-menu > button::after {
    content: " ▾";
    font-size: var(--fs-xs);
  }

  /* Dropdown + submenu popovers: a padded card of rounded hover items, so a
     side-flyout submenu is never clipped (no overflow:hidden) and the Table
     menu's groups read as a menu, not a button strip. overflow-y:auto + the
     measured max-height (inline) mean a menu taller than the room scrolls
     instead of clipping (#1227). */
  .toolbar-menu-popover,
  .toolbar-submenu-popover {
    position: absolute;
    z-index: 30;
    display: grid;
    min-width: 178px;
    padding: 5px;
    border: 1px solid var(--toolbar-border);
    border-radius: 8px;
    background: var(--toolbar-surface);
    box-shadow: var(--toolbar-elev);
    overflow-y: auto;
  }

  /* Opens downward by default (toward the content); .drop-up flips it above the
     trigger. Direction is measured per-open (#1227), not tied to the toolbar's
     own above/below placement. */
  .toolbar-menu-popover {
    left: 0;
    top: calc(100% + 6px);
  }

  .toolbar-menu-popover.drop-up {
    top: auto;
    bottom: calc(100% + 6px);
  }

  /* The rightmost top-level menu (the Table menu when in a table) anchors its
     dropdown to the right so it opens inward instead of clipping off the frame
     edge; its submenus flip left in turn (.toolbar-submenu-popover.flip). */
  .selection-toolbar > .toolbar-menu:last-child .toolbar-menu-popover {
    left: auto;
    right: 0;
  }

  .toolbar-submenu {
    position: relative;
    display: grid;
  }

  .toolbar-submenu-popover {
    top: -6px;
    left: calc(100% + 5px);
  }

  .toolbar-submenu-popover.flip {
    left: auto;
    right: calc(100% + 5px);
  }

  /* Submenu near the viewport bottom: anchor its bottom to the parent row and
     open upward instead of clipping (#1227). */
  .toolbar-submenu-popover.flip-up {
    top: auto;
    bottom: -6px;
  }

  .toolbar-menu-popover button,
  .toolbar-submenu-popover button {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    width: 100%;
    min-width: 0;
    height: 32px;
    padding: 0 10px;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: var(--toolbar-text);
    font-size: var(--fs-md);
    font-weight: 600;
    text-align: left;
    white-space: nowrap;
    cursor: pointer;
  }

  .toolbar-menu-popover button:hover,
  .toolbar-submenu-popover button:hover,
  .toolbar-menu-popover button.open {
    background: var(--toolbar-hover);
  }

  .toolbar-menu-popover button.danger,
  .toolbar-submenu-popover button.danger {
    color: var(--toolbar-danger-text);
  }

  .toolbar-menu-popover button.has-submenu::after {
    content: "▸";
    margin-left: auto;
    padding-left: 16px;
    color: var(--toolbar-text-muted);
    font-size: var(--fs-xs);
  }

  .toolbar-menu-sep {
    height: 1px;
    margin: 4px 8px;
    background: var(--toolbar-divider);
  }
</style>
