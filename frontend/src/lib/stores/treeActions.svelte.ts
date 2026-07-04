// Tree/node CRUD glue — the manuscript + research tree contracts plus the
// node-creation / cascade-delete / collapse / add-menu actions lifted out of
// App.svelte (#14 P0). A singleton rune controller (mirrors editorPanes /
// projectSession / aiSettings / todoActions): it owns the two TreeConfig
// objects consumed by Tree.svelte, the floating add-menu popover state, the
// per-project group-collapse state (persisted to localStorage), and the
// create / delete / lore→research-migrate actions.
//
// Editor-pane coupling (close panes pointing at a doomed subtree, open the
// created or migrated node) goes through the editorPanes controller as a plain
// module import — the proven precedent. App injects only `run` (its api-error
// wrapper) and `setStatus`.

import { get } from "svelte/store";
import { api } from "@/lib/api";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import {
  refreshResearchStructure,
  refreshStructure,
  setResearchStructure,
  setStructure,
  structureStore,
  researchStructureStore,
} from "@/lib/stores/structure";
import { refreshLoreEntries, setLoreEntries } from "@/lib/stores/lore";
import { refreshPromptEntries } from "@/lib/stores/prompts";
import { refreshAssistantEntries } from "@/lib/stores/assistants";
import { refreshTodos } from "@/lib/stores/todos";
import { metadataSchemaStore } from "@/lib/stores/schema";
import {
  collectNodeIdSet,
  collectSceneIdSet,
  entryTypeName,
} from "@/lib/utils/treeHelpers";
import type { TreeConfig } from "@/components/panes/Tree.svelte";
import type {
  LoreEntrySummary,
  StructureNode,
  StructureNodeDeletePreview,
} from "@/lib/types";

const TREE_COLLAPSE_LS_PREFIX = "treeCollapse:";
// Defer a group's collapse-toggle past the browser's dblclick recognition
// window so a fast second click can cancel it and open the editor instead.
const DBLCLICK_GUARD_MS = 300;

class TreeActions {
  // Floating add-menu popover, shared across both trees. `position: fixed`
  // coordinates are captured at click time so the menu sidesteps any ancestor
  // `overflow: hidden`. App's document-level mousedown handler closes it.
  addMenuOpenFor = $state<string | null>(null);
  addMenuPosition = $state<{ top: number; right: number } | null>(null);

  // Outline / research group-header collapse, keyed by StructureNode.id.
  // Structure collapse is persisted per-project to localStorage; research
  // collapse is in-memory only (matches the pre-extraction behaviour).
  collapsedStructureNodes = $state<Record<string, boolean>>({});
  collapsedResearchNodes = $state<Record<string, boolean>>({});

  // ---- Injected host hooks (set in App.onMount) ----
  run: (action: () => Promise<void>) => Promise<boolean> = async (action) => {
    await action();
    return true;
  };
  setStatus: (message: string) => void = () => {};

  // The project whose collapse state is currently loaded, so toggles persist
  // back to the right localStorage key.
  #projectPath = "";
  #pendingCollapseTimeoutId: ReturnType<typeof setTimeout> | null = null;

  // ---- Node creation ----
  async newLoreEntry(entryType: string): Promise<void> {
    await this.run(async () => {
      const entry = await api.createLoreEntry("New Entry", entryType);
      await refreshLoreEntries();
      await editorPanes.openLore(entry.id);
    });
  }

  async newPromptEntry(entryType: string): Promise<void> {
    await this.run(async () => {
      const created = await api.createPromptEntry("Untitled Prompt", entryType);
      await refreshPromptEntries();
      await editorPanes.openPrompt(created.id);
    });
  }

  async newAssistantEntry(): Promise<void> {
    await this.run(async () => {
      const created = await api.createAssistantEntry("Untitled assistant");
      await refreshAssistantEntries();
      await editorPanes.openAssistant(created.id);
    });
  }

  // ---- Lore → Research migration ----
  // Confirms before running because the v1 note schema is minimal — aliases /
  // related_entries / context_policy on the source are intentionally dropped.
  // The cascade preview surfaces what'll be lost so the user can cancel.
  requestMoveLoreNoteToResearch(entry: LoreEntrySummary): void {
    const droppable: string[] = [];
    const meta = entry.metadata ?? {};
    if (Array.isArray(meta.aliases) && meta.aliases.length > 0) droppable.push("aliases");
    if (Array.isArray(meta.related_entries) && meta.related_entries.length > 0) droppable.push("related_entries");
    if (typeof meta.context_policy === "string" && meta.context_policy && meta.context_policy !== "auto") {
      droppable.push("context_policy");
    }
    const cascadeNote = droppable.length > 0
      ? `\n\nThe following metadata will be dropped (research notes only carry title + body + tags): ${droppable.join(", ")}.`
      : "";
    confirmService.request({
      title: "Move to Research",
      message: `Move "${entry.title}" out of Lore and into the Research tree?${cascadeNote}`,
      details: [],
      confirmLabel: "Move to Research",
      destructive: droppable.length > 0,
      onConfirm: async () => {
        // Close the lore entry's editor pane first so it doesn't dangle
        // on a deleted file. The new research note will open in its own
        // pane after the migration.
        editorPanes.panes.forEach((pane) => {
          if (pane.document?.type === "lore" && pane.document.id === entry.id) {
            editorPanes.tearDown(pane.id);
          }
        });
        await this.run(async () => {
          const result = await api.moveLoreNoteToResearch(entry.id);
          setLoreEntries(result.lore.entries);
          setResearchStructure(result.tree);
          // Open the new note in the editor so the user sees the result.
          await editorPanes.openResearchNote(result.note_id);
          this.setStatus(result.dropped_fields.length > 0
            ? `Moved "${entry.title}" to Research (dropped ${result.dropped_fields.join(", ")})`
            : `Moved "${entry.title}" to Research`);
        });
      },
    });
  }

  // ---- Cascade delete ----
  // Generic cascade-delete confirmation. Manuscript and research differ only
  // in noun choice ("scene"/"sub-container" vs "note"/"topic"), so
  // config.cascadeLabels covers it. The actual delete fans out through
  // #performTreeDelete, which closes any editor panes that point at the doomed
  // subtree before calling the kind-specific delete API.
  async requestDeleteTreeNode(config: TreeConfig, node: StructureNode): Promise<void> {
    let preview: StructureNodeDeletePreview | null = null;
    try {
      preview = await config.api.cascadePreview(node.id);
    } catch (error) {
      console.warn("Failed to fetch cascade preview", error);
    }
    const typeName = entryTypeName(node.type, get(metadataSchemaStore));
    const leafCount = preview?.descendant_scene_count ?? 0;
    const containerCount = preview?.descendant_container_count ?? 0;
    const leafLabels = config.cascadeLabels.leaf;
    const containerLabels = config.cascadeLabels.container;
    const cascadeParts: string[] = [];
    if (leafCount > 0) cascadeParts.push(`${leafCount} ${leafCount === 1 ? leafLabels.singular : leafLabels.plural}`);
    if (containerCount > 0) cascadeParts.push(`${containerCount} ${containerCount === 1 ? containerLabels.singular : containerLabels.plural}`);
    const backlinks = preview?.backlinks ?? [];

    let message = `Delete ${typeName} "${node.title}"?`;
    if (cascadeParts.length > 0) {
      message += `\n\nThis will also permanently remove ${cascadeParts.join(" and ")} inside it.`;
    } else if (node.scene_id) {
      message += ` This removes the ${leafLabels.singular} file from the project.`;
    } else {
      message += ` This removes the ${containerLabels.singular} from the project.`;
    }
    if (backlinks.length > 0) {
      message += `\n\n${backlinks.length} ${backlinks.length === 1 ? "entry references" : "entries reference"} content that will be deleted — those links will break:`;
    }

    confirmService.request({
      title: `Delete ${typeName}`,
      message,
      details: backlinks.map((link) => `${link.title} — ${link.field_name}`),
      confirmLabel: `Delete ${typeName}`,
      destructive: true,
      onConfirm: () => this.#performTreeDelete(config, node),
    });
  }

  async #performTreeDelete(config: TreeConfig, node: StructureNode): Promise<void> {
    // Close editor panes whose underlying leaf is doomed before the API
    // call so the panes don't dangle on a missing scene/note.
    const doomedSceneIds = collectSceneIdSet(node);
    editorPanes.panes.forEach((pane) => {
      if (
        pane.scene
        && pane.document?.type === config.kind
        && doomedSceneIds.has(pane.scene.id)
      ) {
        editorPanes.tearDown(pane.id);
      }
    });
    if (config.containerHasEditor) {
      // Manuscript Acts/Chapters can open as structure_node editor panes
      // — close those too if their node id falls inside the doomed subtree.
      const doomedNodeIds = collectNodeIdSet(node);
      editorPanes.panes.forEach((pane) => {
        if (pane.document?.type === "structure_node" && doomedNodeIds.has(pane.document.id)) {
          editorPanes.tearDown(pane.id);
        }
      });
    }
    const next = await config.api.delete(node.id);
    config.applyStructure(next);
    if (config.afterDelete) {
      await config.afterDelete();
    }
    this.setStatus("Deleted");
  }

  // ---- Add menu ----
  toggleAddMenu(nodeId: string, event?: MouseEvent): void {
    if (this.addMenuOpenFor === nodeId) {
      this.addMenuOpenFor = null;
      this.addMenuPosition = null;
      return;
    }
    this.addMenuOpenFor = nodeId;
    const anchor = event?.currentTarget;
    if (anchor instanceof HTMLElement) {
      const rect = anchor.getBoundingClientRect();
      // The popover anchors to the button's right edge and drops below.
      // If there isn't room below (less than 200px before the viewport
      // bottom), flip above the button instead.
      const popoverHeight = 180;
      const fitsBelow = window.innerHeight - rect.bottom > popoverHeight;
      this.addMenuPosition = {
        top: fitsBelow ? rect.bottom + 4 : rect.top - popoverHeight - 4,
        right: window.innerWidth - rect.right,
      };
    } else {
      this.addMenuPosition = null;
    }
  }

  closeAddMenu(): void {
    this.addMenuOpenFor = null;
    this.addMenuPosition = null;
  }

  // ---- Group collapse (persisted per-project) ----
  loadCollapseForProject(path: string): void {
    this.#projectPath = path;
    this.collapsedStructureNodes = this.#loadCollapsed(path);
  }

  toggleStructureNodeCollapse(nodeId: string): void {
    this.collapsedStructureNodes = {
      ...this.collapsedStructureNodes,
      [nodeId]: !this.collapsedStructureNodes[nodeId],
    };
    this.#saveCollapsed();
  }

  // Tree-row click → defer the collapse toggle past the dblclick window so a
  // fast second click can cancel it and open the editor instead. Without the
  // defer the row visibly toggles collapsed-state for ~100ms before the editor
  // opens on top.
  deferStructureNodeCollapse(nodeId: string): void {
    if (this.#pendingCollapseTimeoutId !== null) {
      clearTimeout(this.#pendingCollapseTimeoutId);
    }
    this.#pendingCollapseTimeoutId = setTimeout(() => {
      this.#pendingCollapseTimeoutId = null;
      this.toggleStructureNodeCollapse(nodeId);
    }, DBLCLICK_GUARD_MS);
  }

  handleStructureNodeDblClick(nodeId: string): void {
    if (this.#pendingCollapseTimeoutId !== null) {
      clearTimeout(this.#pendingCollapseTimeoutId);
      this.#pendingCollapseTimeoutId = null;
    }
    void this.run(() => editorPanes.openStructureNode(nodeId));
  }

  #loadCollapsed(path: string): Record<string, boolean> {
    if (!path) return {};
    try {
      const raw = localStorage.getItem(TREE_COLLAPSE_LS_PREFIX + path);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  #saveCollapsed(): void {
    if (!this.#projectPath) return;
    try {
      localStorage.setItem(TREE_COLLAPSE_LS_PREFIX + this.#projectPath, JSON.stringify(this.collapsedStructureNodes));
    } catch {
      // Quota / private-browsing — silently degrade to in-memory only.
    }
  }

  // ---- Tree configs (the per-kind contract consumed by Tree.svelte) ----
  // App owns the structure data (passed to Tree separately); these wire the
  // kind-specific api + the editor-pane / collapse callbacks that live here.
  manuscriptTree: TreeConfig = {
    kind: "scene",
    leafType: "scene:scene",
    getStructure: () => get(structureStore),
    applyStructure: (next) => { setStructure(next); },
    refresh: refreshStructure,
    api: {
      create: api.createStructureNode.bind(api),
      rename: api.renameStructureNode.bind(api),
      move: api.moveStructureNode.bind(api),
      cascadePreview: api.cascadeDeletePreview.bind(api),
      delete: api.deleteStructureNode.bind(api),
    },
    openLeaf: (sceneId) => editorPanes.openScene(sceneId),
    onGroupClick: (nodeId) => this.deferStructureNodeCollapse(nodeId),
    onGroupDblClick: (nodeId) => this.handleStructureNodeDblClick(nodeId),
    cascadeLabels: {
      leaf: { singular: "scene", plural: "scenes" },
      container: { singular: "sub-container", plural: "sub-containers" },
    },
    afterDelete: () => refreshTodos(),
    afterRename: (nodeId, title) => editorPanes.syncRename(nodeId, title),
    supportsDrag: true,
    showStatusStripe: true,
    containerHasEditor: true,
    inlineRenameOnLeafCreate: true,
    rootAddMenuKey: "__root__",
  };

  researchTree: TreeConfig = {
    kind: "research",
    leafType: "research:note",
    getStructure: () => get(researchStructureStore),
    applyStructure: (next) => { setResearchStructure(next); },
    refresh: refreshResearchStructure,
    api: {
      create: api.createResearchNode.bind(api),
      rename: api.renameResearchNode.bind(api),
      cascadePreview: api.cascadeResearchDeletePreview.bind(api),
      delete: api.deleteResearchNode.bind(api),
    },
    openLeaf: (sceneId) => editorPanes.openResearchNote(sceneId),
    onGroupClick: (nodeId) => {
      this.collapsedResearchNodes = {
        ...this.collapsedResearchNodes,
        [nodeId]: !this.collapsedResearchNodes[nodeId],
      };
    },
    // Research has no container editor to open, so a group double-click renames.
    groupDblClickRenames: true,
    cascadeLabels: {
      leaf: { singular: "note", plural: "notes" },
      container: { singular: "topic", plural: "topics" },
    },
    supportsDrag: false,
    showStatusStripe: false,
    containerHasEditor: false,
    inlineRenameOnLeafCreate: false,
    rootAddMenuKey: "__research_root__",
  };
}

export const treeActions = new TreeActions();
