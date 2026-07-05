// Panel registry for the tiled workspace (#32). Regions self-register their
// rendered content (title + body + optional tab-bar actions) here, keyed by the
// same panel id the layout tree references. This decouples *where* a region is
// tiled (workspaceLayout) from *what* it renders (its owning component), and
// lets content that lives outside App — e.g. SchemaPanes — participate without
// prop-drilling its snippets up the tree.
//
// It also delivers the design-language extension guarantee: a saved layout that
// names a region no component has registered yet simply renders an empty slot
// instead of erroring — the region "joins" the moment its owner mounts.
//
// Editor documents are NOT registered here; they are a distinct surface class
// (dynamic, always closable) handled by the editor hooks on <Workspace/>.

import type { Snippet } from "svelte";
import type { PanelId } from "@/lib/types";

export type RegionEntry = {
  title: string;
  body: Snippet;
  // Trailing tab-bar affordances (view switcher, add buttons, …).
  actions?: Snippet;
  // Permanent regions (Draft, Lore) omit this; on-demand ones (Prompts, Chats)
  // set closable + an onClose that also resets their open-state flag.
  closable?: boolean;
  onClose?: () => void;
};

class PanelRegistry {
  entries = $state<Record<PanelId, RegionEntry>>({});

  register(id: PanelId, entry: RegionEntry): void {
    this.entries = { ...this.entries, [id]: entry };
  }

  unregister(id: PanelId): void {
    const { [id]: _removed, ...rest } = this.entries;
    this.entries = rest;
  }

  get(id: PanelId): RegionEntry | undefined {
    return this.entries[id];
  }
}

export const panelRegistry = new PanelRegistry();
