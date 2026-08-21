// Per-project layout of the editor's Details rail (#1246): which side it docks
// (right | bottom), its size on that axis, and whether it's collapsed. Bottom
// dock exists so the long-text metadata fields get the full editor width instead
// of a cramped ~280px scroll box.
//
// Persisted per project, mirroring `workspaceLayout` (the whole pane layout is
// already per-project), so a writer's preferred rail layout survives reloads and
// scene switches. A singleton rune store: `App` calls `loadForProject` on open,
// and `EditorRail` / `NodeEditor` read and mutate it directly — no prop drilling.

export type RailSide = "right" | "bottom";

const STORAGE_PREFIX = "lwa.editorRail:";

// Width governs the right dock, height the bottom dock. Both clamp so the rail
// can never squeeze the body to nothing; defaults match the pre-#1246 rail width.
export const RAIL_WIDTH_MIN = 220;
export const RAIL_WIDTH_MAX = 560;
export const RAIL_WIDTH_DEFAULT = 280;
export const RAIL_HEIGHT_MIN = 140;
export const RAIL_HEIGHT_MAX = 520;
export const RAIL_HEIGHT_DEFAULT = 240;

function clamp(value: unknown, min: number, max: number, fallback: number): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

interface RailSnapshot {
  side?: unknown;
  width?: unknown;
  height?: unknown;
  collapsed?: unknown;
}

class EditorRailLayout {
  side = $state<RailSide>("right");
  width = $state(RAIL_WIDTH_DEFAULT);
  height = $state(RAIL_HEIGHT_DEFAULT);
  /** The author's explicit collapse preference for this project. `NodeEditor`
   *  reconciles it with per-body-shape defaults (chat/view open collapsed). */
  collapsed = $state(false);

  #storageKey: string | null = null;

  loadForProject(path: string): void {
    this.#storageKey = path ? STORAGE_PREFIX + path : null;
    let snap: RailSnapshot | null = null;
    try {
      snap = this.#storageKey ? (JSON.parse(localStorage.getItem(this.#storageKey) ?? "null") as RailSnapshot) : null;
    } catch {
      snap = null;
    }
    this.side = snap?.side === "bottom" ? "bottom" : "right";
    this.width = clamp(snap?.width, RAIL_WIDTH_MIN, RAIL_WIDTH_MAX, RAIL_WIDTH_DEFAULT);
    this.height = clamp(snap?.height, RAIL_HEIGHT_MIN, RAIL_HEIGHT_MAX, RAIL_HEIGHT_DEFAULT);
    this.collapsed = snap?.collapsed === true;
  }

  setSide(side: RailSide): void {
    this.side = side;
    this.#persist();
  }

  setWidth(width: number): void {
    this.width = clamp(width, RAIL_WIDTH_MIN, RAIL_WIDTH_MAX, RAIL_WIDTH_DEFAULT);
    this.#persist();
  }

  setHeight(height: number): void {
    this.height = clamp(height, RAIL_HEIGHT_MIN, RAIL_HEIGHT_MAX, RAIL_HEIGHT_DEFAULT);
    this.#persist();
  }

  setCollapsed(collapsed: boolean): void {
    this.collapsed = collapsed;
    this.#persist();
  }

  #persist(): void {
    if (!this.#storageKey) return;
    try {
      localStorage.setItem(
        this.#storageKey,
        JSON.stringify({ side: this.side, width: this.width, height: this.height, collapsed: this.collapsed }),
      );
    } catch {
      // localStorage unavailable — the in-memory state still drives this session.
    }
  }
}

export const editorRailLayout = new EditorRailLayout();
