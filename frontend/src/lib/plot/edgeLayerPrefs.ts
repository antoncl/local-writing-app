// Which edge layers the writer has toggled on (ADR-0048 S7 Slice 6a). Layer
// VISIBILITY is a viewing mode, not project canon — so it lives in localStorage
// (browser-scoped, survives reloads and cache rebuilds, never touches `.cache` or
// the project files), the same way the app stores its other view prefs (the hidden
// Library, dismissed confirmations). One global key: it's "how I like to read a
// board," not a per-project curation. Default is EMPTY — a quiet board that the
// reader/pantser flow leaves untouched until a layer is deliberately turned on.
//
// The storage seam is injected (defaulting to the browser's localStorage) so this
// is unit-testable without a DOM, and so a disabled / SSR store degrades to "no
// pref" rather than throwing.

import { EDGE_LAYERS, type EdgeLayer } from "./plotBoardEdges";

const KEY = "plotBoard.edgeLayers";

type PrefStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function defaultStorage(): PrefStorage | null {
  try {
    return typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    return null; // storage access can throw (privacy modes) — treat as absent.
  }
}

export function loadEdgeLayers(storage: PrefStorage | null = defaultStorage()): Set<EdgeLayer> {
  if (!storage) return new Set();
  try {
    const raw = storage.getItem(KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    const known = new Set<string>(EDGE_LAYERS);
    return new Set(
      (Array.isArray(parsed) ? parsed : []).filter(
        (x): x is EdgeLayer => typeof x === "string" && known.has(x),
      ),
    );
  } catch {
    return new Set(); // corrupt / unavailable → nothing active, never throw.
  }
}

export function saveEdgeLayers(
  layers: Set<EdgeLayer>,
  storage: PrefStorage | null = defaultStorage(),
): void {
  if (!storage) return;
  try {
    if (layers.size > 0) storage.setItem(KEY, JSON.stringify([...layers]));
    else storage.removeItem(KEY); // empty ⇒ drop the key, leaving no trace.
  } catch {
    // Storage disabled / quota — the pref just won't persist; not fatal.
  }
}

// Toggle one layer, returning a NEW set (so a rune assignment sees the change).
export function toggleEdgeLayer(layers: Set<EdgeLayer>, layer: EdgeLayer): Set<EdgeLayer> {
  const next = new Set(layers);
  if (next.has(layer)) next.delete(layer);
  else next.add(layer);
  return next;
}
