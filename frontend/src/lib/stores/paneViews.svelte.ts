// Pane view-selection state (0.5.0 step 4, #81, doc §5). Lore / Draft /
// Assistants each expose a switcher over the implicit default view + the saved
// `view` nodes anchored to that pane's kind. This controller owns:
//   - the saved-view roster per kind (summaries), loaded from the backend;
//   - the full ViewSpec per view id, prefetched so the selected view evaluates
//     synchronously with no per-view fetch;
//   - the *selected* view per kind, persisted in UI state (localStorage) — the
//     views are project data, the selection is not (ADR-0022).
//
// Reactivity bridge: this is rune `$state`. App.svelte (runes) reads `specFor`
// inside `$derived` and passes the result as a prop to the (legacy `$:`) pane
// components, which react to prop changes — sidestepping the cross-module
// rune-tracking trap (feedback_svelte5_reactivity_traps).

import { api } from "@/lib/api";
import { defaultView } from "@/lib/views/evaluateView";
import { builtinSpecFor, isBuiltinExtraViewId } from "@/lib/views/builtinViews";
import type { MetadataSchema, ViewAppearance, ViewNodeSummary, ViewSpec } from "@/lib/types";

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

// Kinds with a persisted selection, so restoration also covers a kind whose only
// non-default selection is a frontend-synthesized built-in (e.g. "Openable
// chats" when the project has no saved chat views to enumerate).
function storedSelectionKinds(): string[] {
  try {
    const kinds: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key?.startsWith(STORAGE_PREFIX)) kinds.push(key.slice(STORAGE_PREFIX.length));
    }
    return kinds;
  } catch {
    return [];
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
  // A view's chosen render layout by view id (ADR-0069), from its `ui.appearance`.
  // Reactive so the pane re-renders at the new mode/density the moment it changes.
  appearances = $state<Map<string, ViewAppearance>>(new Map());

  #loadedPath: string | null = null;

  // Load (or switch to) a project's saved views + restore its persisted
  // selection. Idempotent per path; call again to force a refresh.
  async loadForProject(path: string): Promise<void> {
    this.#loadedPath = path;
    await this.reload();
    const restored: Record<string, string | null> = {};
    for (const kind of new Set([...Object.keys(this.views), ...storedSelectionKinds()])) {
      const saved = loadSelection(kind);
      // A built-in extra (e.g. "Openable chats") is a valid selection even though
      // it is not a saved node — it is frontend-synthesized (builtinViews).
      const valid = saved && ((this.views[kind] ?? []).some((v) => v.id === saved) || isBuiltinExtraViewId(saved));
      restored[kind] = valid ? saved : null;
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
    // switcher renders them read-only (Duplicate, not Edit), so they stay in both
    // the roster and the spec map. `selected===null` still means the pane's default.
    const byKind: Record<string, ViewNodeSummary[]> = {};
    for (const v of entries) (byKind[v.view_kind] ??= []).push(v);
    for (const list of Object.values(byKind)) {
      list.sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
    }
    this.views = byKind;

    // The list summary already carries each view's spec (#95), so evaluation
    // is synchronous with no per-view fetch.
    const map = new Map<string, ViewSpec>();
    const appearanceMap = new Map<string, ViewAppearance>();
    for (const v of entries) {
      if (v.spec) map.set(v.id, v.spec);
      // Retain the ui.appearance the summary already ships (ADR-0069) — reload()
      // dropped `v.ui` before, so a saved layout was invisible to the pane.
      if (v.ui?.appearance) appearanceMap.set(v.id, v.ui.appearance);
    }
    this.specs = map;
    this.appearances = appearanceMap;

    // Drop any selection that no longer resolves — but keep frontend-synthesized
    // built-in extras, which are never in the backend spec map.
    for (const [kind, id] of Object.entries(this.selected)) {
      if (id && !map.has(id) && !isBuiltinExtraViewId(id)) this.select(kind, null);
    }
  }

  reset(): void {
    this.#loadedPath = null;
    this.views = {};
    this.selected = {};
    this.specs = new Map();
    this.appearances = new Map();
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
      // A saved view's spec, else a built-in extra's synthesized spec.
      const spec = this.specs.get(id) ?? builtinSpecFor(kind, id, schema);
      if (spec) return spec;
    }
    return defaultView(kind, schema);
  }

  // The render layout a pane should apply (ADR-0069): the resolved view's stored
  // `ui.appearance`, or null when it has set none (⇒ the pane keeps its default
  // mode/density). Keyed the same way fold state is — the selected view, or the
  // pane's `view_default_<kind>`.
  appearanceFor(kind: string): ViewAppearance | null {
    return this.appearances.get(this.resolvedViewId(kind)) ?? null;
  }

  // Set (part of) the resolved view's appearance and persist it. Merges the
  // patch onto the current appearance so the control can set `mode` and
  // `density` independently. The write carries ONLY `appearance`; the backend
  // merges it into the ui blob, so a saved fold state (`collapsed`) survives
  // (ADR-0069). Optimistic — reverts the local map if the write fails.
  async setAppearance(kind: string, patch: Partial<ViewAppearance>): Promise<void> {
    const id = this.resolvedViewId(kind);
    const prior = this.appearances.get(id) ?? null;
    const next: ViewAppearance = { ...(prior ?? {}), ...patch };
    this.appearances = new Map(this.appearances).set(id, next);
    try {
      await api.updateViewUi(id, { appearance: next });
    } catch {
      // Restore the prior value (or drop the key if there was none).
      const reverted = new Map(this.appearances);
      if (prior) reverted.set(id, prior);
      else reverted.delete(id);
      this.appearances = reverted;
    }
  }
}

export const paneViews = new PaneViewsController();
