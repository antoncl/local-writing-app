// Persisted open/closed state for the metadata rail's collapsible sections and
// reference fields (#1444). Each section tracked open/closed with component-local
// `$state`, and `NodeEditor` wraps the panels in `{#key scene.id}` — so switching
// the open node remounted them back to their default, and nothing survived a
// reload. The rail's own geometry (side / width / collapsed) already persists via
// `editorRailLayout`; this extends the same treatment to the inner sections.
//
// A panel reads its expanded state from here (with its own default) and toggles
// through it. The `{#key}` remount stays — on remount the value is re-read from
// the store, so it survives node switches; `localStorage` carries it across
// reloads. Only the expanded flag is lifted out, so per-node state that SHOULD
// reset (an open ＋New popover) still does.
//
// Global — one key, not per-project (mirroring how a collapsed section reads as a
// "how I like my rail" preference, not project data). Keys are a stable section
// id (`references`, `conversations`, `staged-changes`) or `field:<fieldId>` for a
// reference field.

const STORAGE_KEY = "lwa.railSectionCollapse";

// Exported for tests: a fresh instance re-reads localStorage, simulating a reload
// (the app uses the `railSectionCollapse` singleton below).
export class RailSectionCollapse {
  // key -> expanded. An absent key means "use the caller's default".
  #expanded = $state<Record<string, boolean>>({});

  constructor() {
    this.#load();
  }

  /** The section's expanded state, or `fallback` when the writer hasn't set one. */
  isExpanded(key: string, fallback: boolean): boolean {
    const v = this.#expanded[key];
    return typeof v === "boolean" ? v : fallback;
  }

  toggle(key: string, fallback: boolean): void {
    this.set(key, !this.isExpanded(key, fallback));
  }

  set(key: string, expanded: boolean): void {
    this.#expanded[key] = expanded;
    this.#persist();
  }

  #load(): void {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      const parsed = raw ? (JSON.parse(raw) as unknown) : null;
      if (parsed && typeof parsed === "object") {
        const out: Record<string, boolean> = {};
        for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
          if (typeof v === "boolean") out[k] = v;
        }
        this.#expanded = out;
      }
    } catch {
      // localStorage unavailable or corrupt — start empty; defaults still apply.
    }
  }

  #persist(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.#expanded));
    } catch {
      // localStorage unavailable — the in-memory state still drives this session.
    }
  }
}

export const railSectionCollapse = new RailSectionCollapse();
