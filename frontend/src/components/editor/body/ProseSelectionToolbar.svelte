<!--
  ProseSelectionToolbar — presentational floating formatting toolbar shown over
  a text selection in ProseBodyView.

  Purely a view: the host owns the menu state (open/position/placement), builds
  the action list (Bold/Italic/… + the AI "Revise" menu + TODO), and runs the
  commands (wrapping each in focusAndRun so the editor keeps focus). This renders
  the buttons / dropdown menus and calls back on activation. onmousedown handlers
  preventDefault so a click never blurs the editor.
-->
<script lang="ts">
  import { type FloatingMenuState, type ToolbarAction } from "@/lib/editor-core/selectionToolbar";

  interface Props {
    menu: FloatingMenuState;
    actions: ToolbarAction[];
    openMenuId: string | null;
    onRun: (run: () => void | Promise<void>) => void;
    onToggleMenu: (actionId: string) => void;
  }

  let { menu, actions, openMenuId, onRun, onToggleMenu }: Props = $props();
</script>

{#if menu.visible}
  <div class:below={menu.placement === "below"} class="selection-toolbar" style={`left: ${menu.x}px; top: ${menu.y}px;`}>
    <span class="selection-count">{menu.wordCount} {menu.wordCount === 1 ? "word" : "words"}</span>
    {#each actions as action}
      {#if action.kind === "button"}
        <button
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
              onToggleMenu(action.id);
            }}
          >
            {action.label}
          </button>
          {#if openMenuId === action.id}
            <div class:below={menu.placement === "below"} class="toolbar-menu-popover">
              {#each action.items as item}
                <button
                  type="button"
                  onmousedown={(e) => {
                    e.preventDefault();
                    onRun(item.run);
                  }}>{item.label}</button>
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
    box-shadow: 0 14px 28px rgba(25, 40, 35, 0.22);
    transform: translate(-50%, calc(-100% - 8px));
  }

  .selection-toolbar.below {
    transform: translate(-50%, 0);
  }

  .selection-toolbar button,
  .selection-count {
    height: 34px;
    border: 0;
    border-right: 1px solid var(--toolbar-divider);
    border-radius: 0;
    background: transparent;
    color: var(--toolbar-text);
    font-size: 13px;
    font-weight: 700;
    white-space: nowrap;
  }

  .selection-toolbar button {
    min-width: 38px;
    padding: 0 10px;
  }

  .selection-toolbar button:hover {
    background: var(--toolbar-hover);
  }

  .selection-toolbar button.open {
    background: var(--toolbar-hover);
  }

  .selection-count {
    display: inline-flex;
    align-items: center;
    padding: 0 12px;
    color: var(--divider);
  }

  .toolbar-menu {
    position: relative;
  }

  .toolbar-menu > button::after {
    content: " ▾";
    font-size: 11px;
  }

  .toolbar-menu-popover {
    position: absolute;
    left: 0;
    bottom: calc(100% + 6px);
    z-index: 30;
    display: grid;
    min-width: 144px;
    overflow: hidden;
    border: 1px solid var(--toolbar-border);
    border-radius: 7px;
    background: var(--toolbar-surface);
    box-shadow: 0 14px 28px rgba(25, 40, 35, 0.22);
  }

  .toolbar-menu-popover.below {
    top: calc(100% + 6px);
    bottom: auto;
  }

  .toolbar-menu-popover button {
    justify-content: start;
    width: 100%;
    min-width: 0;
    height: 32px;
    border-right: 0;
    border-bottom: 1px solid var(--toolbar-divider);
    text-align: left;
  }

  .toolbar-menu-popover button:last-child {
    border-bottom: 0;
  }
</style>
