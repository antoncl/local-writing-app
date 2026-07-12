// Pane view-selection state (0.5.0 step 4, #81, doc §5). Lore / Draft /
// Assistants each expose a switcher over the implicit default view + the saved
// `view` nodes anchored to that pane's kind. This controller owns:
//   - the saved-view roster per kind (summaries), loaded from the backend;
//   - the full ViewSpec per view id, prefetched so `view_ref` leaves resolve
//     synchronously during evaluation;
//   - the *selected* view per kind, persisted in UI state (localStorage) — the
//     views are project data, the selection is not (ADR-0022).
//
// Reactivity bridge: this is rune `$state`. App.svelte (runes) reads `specFor`
// inside `$derived` and passes the result as a prop to the (legacy `$:`) pane
// components, which react to prop changes — sidestepping the cross-module
// rune-tracking trap (feedback_svelte5_reactivity_traps).

import { api } from "@/lib/api";
import { defaultView } from "@/lib/views/evaluateView";
import type { MetadataSchema, ViewNodeSummary, ViewSpec } from "@/lib/types";

const STORAGE_PREFIX = "paneView.selected."; // + kind

function loadSelection(kind: string): string | null {
  try {
    return localStorage.getItem(STORAGE_PREFIX + kind);
  } catch {
    return null;
  }
}

function saveSelection(kind: string, id: string | null): void {
  try {
    if (id) localStorage.setItem(STORAGE_PREFIX + kind, id);
    else localStorage.removeItem(STORAGE_PREFIX + kind);
  } catch {
    // Storage disabled (private mode) — selection is best-effort.
  }
}

class PaneViewsController {
  // Saved-view summaries grouped by anchor kind (`view_kind`).
  views = $state<Record<string, ViewNodeSummary[]>>({});
  // Selected view id per kind (null = the implicit default view).
  selected = $state<Record<string, string | null>>({});
  // Full specs by view id — reactive so a designer edit (reload) re-evaluates
  // panes even when the selection id is unchanged.
  specs = $state<Map<string, ViewSpec>>(new Map());

  #loadedPath: string | null = null;

  // Resolver for `view_ref` leaves. Stable identity; reads the reactive map.
  resolveView = (viewId: string): ViewSpec | null => this.specs.get(viewId) ?? null;

  // Load (or switch to) a project's saved views + restore its persisted
  // selection. Idempotent per path; call again to force a refresh.
  async loadForProject(path: string): Promise<void> {
    this.#loadedPath = path;
    await this.reload();
    const restored: Record<string, string | null> = {};
    for (const kind of Object.keys(this.views)) {
      const saved = loadSelection(kind);
      restored[kind] = saved && this.views[kind].some((v) => v.id === saved) ? saved : null;
    }
    this.selected = restored;
  }

  // Re-fetch the roster + specs (e.g. after a view is created/edited/deleted).
  async reload(): Promise<void> {
    let entries: ViewNodeSummary[];
    try {
      entries = (await api.listViews()).entries;
    } catch {
      return; // Leave the current roster in place on a transient failure.
    }
    // System default views (ADR-0036 §5) are first-class roster members: the
    // switcher renders them read-only (Duplicate, not Edit) and their spec must
    // resolve for `view_ref` leaves, so they stay in both the roster and the
    // spec map. `selected===null` still means the pane's default.
    const byKind: Record<string, ViewNodeSummary[]> = {};
    for (const v of entries) (byKind[v.view_kind] ??= []).push(v);
    for (const list of Object.values(byKind)) {
      list.sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
    }
    this.views = byKind;

    // The list summary already carries each view's spec (#95), so evaluation
    // (incl. resolving view_ref leaves) is synchronous with no per-view fetch.
    const map = new Map<string, ViewSpec>();
    for (const v of entries) if (v.spec) map.set(v.id, v.spec);
    this.specs = map;

    // Drop any selection that no longer resolves.
    for (const [kind, id] of Object.entries(this.selected)) {
      if (id && !map.has(id)) this.select(kind, null);
    }
  }

  reset(): void {
    this.#loadedPath = null;
    this.views = {};
    this.selected = {};
    this.specs = new Map();
  }

  viewsFor(kind: string): ViewNodeSummary[] {
    return this.views[kind] ?? [];
  }

  selectedId(kind: string): string | null {
    return this.selected[kind] ?? null;
  }

  // The concrete view-node id whose fold state a pane persists to (ADR-0036):
  // the selected saved view, or the pane's `view_default_<kind>` system default
  // when none is selected (materialized on first fold write).
  resolvedViewId(kind: string): string {
    return this.selected[kind] ?? `view_default_${kind}`;
  }

  select(kind: string, id: string | null): void {
    this.selected = { ...this.selected, [kind]: id };
    saveSelection(kind, id);
  }

  // The ViewSpec a pane should render through: the selected view's spec, or the
  // default (the whole roster, manual order) when none is selected. The default
  // is now an explicit `descendants_of:<kind-root>` spec (ADR-0036), so `schema`
  // is threaded through to resolve the kind's root type; without it the resolver
  // falls back to `<kind>:base`.
  specFor(kind: string, schema?: MetadataSchema | null): ViewSpec {
    const id = this.selected[kind];
    if (id) {
      const spec = this.specs.get(id);
      if (spec) return spec;
    }
    return defaultView(kind, schema);
  }
}

export const paneViews = new PaneViewsController();
