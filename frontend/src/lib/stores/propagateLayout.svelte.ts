// Per-project layout of the Propagate pane's list/diff divider (ADR-0091 §7):
// the candidate list column's width in pixels, clamped and persisted like the
// details rail's own width (`editorRailLayout.svelte.ts`, same shape). A
// singleton rune store: `App` calls `loadForProject` on open, `PropagatePane`
// reads and mutates it directly via the shared `SplitHandle`'s callbacks.

const STORAGE_PREFIX = "lwa.propagateSplit:";

// The shipped pane split was 1.25fr : 1fr (5:4) at whatever width the pane
// happened to open at; 320px is that ratio's list column at the pane's
// typical (~720px two-column) width, and sits comfortably inside the clamp.
export const PROPAGATE_LIST_WIDTH_MIN = 220;
export const PROPAGATE_LIST_WIDTH_MAX = 520;
export const PROPAGATE_LIST_WIDTH_DEFAULT = 320;

function clamp(value: unknown, min: number, max: number, fallback: number): number {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

interface PropagateLayoutSnapshot {
  listWidth?: unknown;
}

class PropagateLayout {
  listWidth = $state(PROPAGATE_LIST_WIDTH_DEFAULT);

  #storageKey: string | null = null;

  loadForProject(path: string): void {
    this.#storageKey = path ? STORAGE_PREFIX + path : null;
    let snap: PropagateLayoutSnapshot | null = null;
    try {
      snap = this.#storageKey
        ? (JSON.parse(localStorage.getItem(this.#storageKey) ?? "null") as PropagateLayoutSnapshot)
        : null;
    } catch {
      snap = null;
    }
    this.listWidth = clamp(
      snap?.listWidth,
      PROPAGATE_LIST_WIDTH_MIN,
      PROPAGATE_LIST_WIDTH_MAX,
      PROPAGATE_LIST_WIDTH_DEFAULT,
    );
  }

  setListWidth(px: number): void {
    this.listWidth = clamp(px, PROPAGATE_LIST_WIDTH_MIN, PROPAGATE_LIST_WIDTH_MAX, PROPAGATE_LIST_WIDTH_DEFAULT);
    this.#persist();
  }

  #persist(): void {
    if (!this.#storageKey) return;
    try {
      localStorage.setItem(this.#storageKey, JSON.stringify({ listWidth: this.listWidth }));
    } catch {
      // localStorage unavailable — the in-memory state still drives this session.
    }
  }
}

export const propagateLayout = new PropagateLayout();
