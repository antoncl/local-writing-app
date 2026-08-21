// Tree/node CRUD glue — the manuscript + research tree contracts plus the
// node-creation / cascade-delete / add-menu actions lifted out of
// App.svelte (#14 P0). A singleton rune controller (mirrors editorPanes /
// projectSession / aiSettings / todoActions): it owns the two TreeConfig
// objects consumed by StructureTree.svelte, the floating add-menu popover
// state, and the create / delete / lore→research-migrate actions.
//
// Group collapse is no longer here — it moved onto ViewNodeList's own per-group
// set (#112 / #182 substrate), per-view rather than per-project-localStorage.
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
import { refreshPlotTemplates } from "@/lib/stores/plotTemplates";
import { refreshPlotBoard } from "@/lib/stores/plotBoard";
import { refreshPlotlines } from "@/lib/stores/plotlines";
import { refreshTodos } from "@/lib/stores/todos";
import { refreshChatSessions } from "@/lib/stores/chats";
import { metadataSchemaStore } from "@/lib/stores/schema";
import {
  collectNodeIdSet,
  collectSceneIdSet,
  entryTypeName,
} from "@/lib/utils/treeHelpers";
import type { TreeConfig } from "@/components/panes/StructureTree.svelte";
import type {
  EntryMetadata,
  EntryPatch,
  LoreEntrySummary,
  StructureNode,
  StructureNodeDeletePreview,
} from "@/lib/types";

class TreeActions {
  // ---- Injected host hooks (set in App.onMount) ----
  run: (action: () => Promise<void>) => Promise<boolean> = async (action) => {
    await action();
    return true;
  };
  setStatus: (message: string) => void = () => {};

  // ---- Node creation ----
  async newLoreEntry(entryType: string): Promise<void> {
    await this.run(async () => {
      const entry = await api.createLoreEntry("New Entry", entryType);
      await refreshLoreEntries();
      await editorPanes.openLore(entry.id);
    });
  }

  // ADR-0046 §6.4 / ADR-0048 §5 (#1120): create a node from an AI brainstorm
  // draft, for any flat kind the commit can target — lore entries and plot
  // cards / plotlines. No prior state to diff, so this is the *create branch of
  // the same patch*: mint the empty typed node through its existing create
  // path, merge the reviewed draft (title + structured/long-text fields + body)
  // onto it, PUT once, then refresh the roster and open it. `title` is the one
  // proposed field the save treats top-level; everything else is metadata
  // (references / computed are already excluded from the validated patch, §4).
  //
  // Structural kinds (manuscript scenes, research notes) are out: a flat draft
  // carries no tree position, so their create needs a parent this flow can't
  // supply — an unsupported target fails with a clear message, not a 422.
  // Returns the created node's {id, title}, or null when none was minted.
  async createNodeFromDraft(
    entryType: string,
    patch: EntryPatch,
  ): Promise<{ id: string; title: string } | null> {
    const kind = entryType.split(":")[0];
    if (kind === "lore") {
      // createLoreEntry takes the entry_type, so every lore sub-type mints
      // correctly through the same path.
      return this.#mintFromDraft(entryType, patch, {
        create: (title) => api.createLoreEntry(title, entryType),
        save: (entry, body) => api.saveLoreEntry(entry, body),
        refresh: () => refreshLoreEntries(),
        open: (id) => editorPanes.openLore(id),
      });
    }
    if (entryType === "plot:card" || entryType.startsWith("plot:card:")) {
      return this.#mintFromDraft(entryType, patch, {
        create: (title) => api.createCard(title),
        save: (entry, body) => api.saveCard(entry, body),
        refresh: () => refreshPlotBoard(),
        open: (id) => editorPanes.openPlotCard(id),
      });
    }
    if (entryType === "plot:plotline" || entryType.startsWith("plot:plotline:")) {
      return this.#mintFromDraft(entryType, patch, {
        create: (title) => api.createPlotline(title),
        save: (entry, body) => api.savePlotline(entry, body),
        refresh: async () => {
          await Promise.all([refreshPlotBoard(), refreshPlotlines()]);
        },
        open: (id) => editorPanes.openPlotline(id),
      });
    }
    // A flat brainstorm draft can only create a flat node. Surface the
    // unsupported kind through run()'s error path rather than letting the
    // lore endpoint 422 on a foreign entry_type.
    await this.run(async () => {
      throw new Error(
        `Can't create a ${entryTypeName(entryType, get(metadataSchemaStore))} from a ` +
          `brainstorm draft — only lore entries and plot cards or plotlines can be ` +
          `created this way.`,
      );
    });
    return null;
  }

  // The kind-generic create-from-draft core: every flat kind mints the same
  // way, differing only in the create/save/refresh/open four passed as `ops`.
  // `minted` is captured the moment the save lands, NOT gated on run()'s
  // overall outcome: a failure in the post-create steps (roster refresh, pane
  // open) must still report the node that now exists, so the caller clears its
  // draft (a surviving Create button would mint a duplicate) and stamps the
  // creating chat's `subject` + retitle (#983: the brainstorm that generated a
  // node is that node's first conversation). run() surfaces the error either way.
  async #mintFromDraft<T extends { id: string; title: string; metadata: EntryMetadata }>(
    entryType: string,
    patch: EntryPatch,
    ops: {
      create: (title: string) => Promise<T>;
      save: (entry: T, body: string) => Promise<T>;
      refresh: () => Promise<void>;
      open: (id: string) => Promise<void>;
    },
  ): Promise<{ id: string; title: string } | null> {
    let minted: { id: string; title: string } | null = null;
    await this.run(async () => {
      const fields = { ...patch.fields };
      const proposedTitle =
        typeof fields.title === "string" && fields.title.trim() ? fields.title.trim() : "";
      delete fields.title;
      const finalTitle =
        proposedTitle || `New ${entryTypeName(entryType, get(metadataSchemaStore))}`;
      const created = await ops.create(finalTitle);
      const merged: T = { ...created, metadata: { ...created.metadata, ...fields } };
      const saved = await ops.save(merged, patch.body ?? "");
      minted = { id: saved.id, title: saved.title };
      await ops.refresh();
      await ops.open(saved.id);
      this.setStatus(`Created "${saved.title}"`);
    });
    return minted;
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

  // Blank-create an owned plot template (#918) and open it to author its beats — the
  // non-fork twin of forkPlotTemplate, mirroring newAssistantEntry (a flat roster).
  async newPlotTemplate(): Promise<void> {
    await this.run(async () => {
      const created = await api.createPlotTemplate();
      await refreshPlotTemplates();
      await editorPanes.openPlotTemplate(created.id);
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

  // ---- Tree configs (the per-kind contract consumed by StructureTree.svelte) ----
  // App owns the structure data (passed to Tree separately); these wire the
  // kind-specific api + the editor-pane / collapse callbacks that live here.
  manuscriptTree: TreeConfig = {
    kind: "manuscript",
    leafType: "manuscript:scene",
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
    onGroupDblClick: (nodeId) => void this.run(() => editorPanes.openStructureNode(nodeId)),
    cascadeLabels: {
      leaf: { singular: "scene", plural: "scenes" },
      container: { singular: "sub-container", plural: "sub-containers" },
    },
    afterDelete: () => {
      // A deleted scene may have cascade-deleted its attached chats (#1078); drop
      // them from the Chats pane (#1087).
      void refreshChatSessions();
      return refreshTodos();
    },
    afterRename: (nodeId, title) => editorPanes.syncRename(nodeId, title),
    supportsDrag: true,
    showStatusStripe: true,
    containerHasEditor: true,
    inlineRenameOnLeafCreate: true,
    rootAddMenuKey: "__root__",
    persistCollapse: true,
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
      move: api.moveResearchNode.bind(api),
      cascadePreview: api.cascadeResearchDeletePreview.bind(api),
      delete: api.deleteResearchNode.bind(api),
    },
    openLeaf: (sceneId) => editorPanes.openResearchNote(sceneId),
    // Research has no container editor to open, so a group double-click renames.
    groupDblClickRenames: true,
    cascadeLabels: {
      leaf: { singular: "note", plural: "notes" },
      container: { singular: "topic", plural: "topics" },
    },
    // A deleted note may have cascade-deleted attached chats (#1078/#1087).
    afterDelete: () => refreshChatSessions(),
    supportsDrag: true,
    showStatusStripe: false,
    containerHasEditor: false,
    inlineRenameOnLeafCreate: false,
    rootAddMenuKey: "__research_root__",
    persistCollapse: false,
  };
}

export const treeActions = new TreeActions();
