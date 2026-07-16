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
import type { PanelId, ViewSpec } from "@/lib/types";

// An explicit-view pane declares itself here (ADR-0022 / ADR-0032 §D Amdt 1):
// the pane's anchor `kind` drives BOTH the handle-bar view selector AND the spec
// its body renders through, from ONE source — so the selector is no longer a
// per-pane widget App hand-places (the drift seam #258 closes). The central
// region outlets (RegionActions / RegionBody) render the switcher and resolve
// `paneViews.specFor(kind, schema)` — reading the schema from `metadataSchemaStore`
// so it stays live (the registry entry is captured once at mount, so a reactive
// value baked in here would freeze). `switcher` gates *exposure* (ADR-0022 v1:
// Draft/Lore/Assistants) — a config on the one mechanism, not a licence to
// re-place it; a fixed-view pane (Research/Prompts) omits it and just receives
// its resolved default spec.
export type RegionView = {
  kind: string;
  switcher?: boolean;
};

export type RegionEntry = {
  title: string;
  // Receives the resolved ViewSpec when the entry declares `view`; a non-view
  // pane ignores the argument.
  body: Snippet<[ViewSpec | undefined]>;
  // Trailing tab-bar affordances (add buttons, …). The view selector is NOT
  // here anymore — it comes from `view.switcher`, rendered centrally.
  actions?: Snippet;
  // Present ⇒ an explicit-view pane; the outlets render the selector + spec.
  view?: RegionView;
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
