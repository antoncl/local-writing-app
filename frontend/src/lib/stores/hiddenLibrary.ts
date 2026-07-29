// Per-project suppression of built-in Library nodes (ADR-0049 slice 3, #680).
//
// "Hide" is a VIEW concern, not canon — so it is stored the way the app already
// stores "don't show this again" (confirmService): localStorage, browser-scoped,
// keyed by the open project's path. Consequences that fall out of that choice,
// all deliberate:
//   - The node index stays COMPLETE. Hide never removes a node from the resolved
//     set — it is a presentation filter over it, so "Show hidden" can reveal the
//     row to un-hide, a still-referenced prompt keeps resolving by id, and clone
//     is reachable once shown.
//   - It survives reloads and cache rebuilds (localStorage is not `.cache`), but
//     stays local to this browser — a curated shelf is per-workstation, exactly
//     like a dismissed confirmation. Promotable to on-disk later by moving only
//     the SOURCE of the set; the filter, the affordances, and the UI are unchanged.
//
// A classic store (not a rune controller) so it composes with `derived` and so
// components read the reactive set as `$hiddenLibraryStore`.

import { writable, type Readable } from "svelte/store";

const KEY_PREFIX = "libraryHidden:";

// The open project's path. Hide is per-project, so localStorage keys by it and
// two projects on one machine curate independently. Null before any project is
// open, where hide is inert.
let currentPath: string | null = null;

// Reactive mirror of the current project's hidden-id set. Components read it via
// `$hiddenLibraryStore` to filter/mark rows; the prompt-resolution context reads
// a snapshot of it to drop hidden prompts from discovery surfaces.
const store = writable<Set<string>>(new Set());
export const hiddenLibraryStore: Readable<Set<string>> = { subscribe: store.subscribe };

function readFromStorage(path: string): Set<string> {
  try {
    const raw = localStorage.getItem(KEY_PREFIX + path);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    return new Set(
      Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [],
    );
  } catch {
    // Corrupt / unavailable storage — treat as "nothing hidden" rather than throw.
    return new Set();
  }
}

function writeToStorage(path: string, ids: Set<string>): void {
  try {
    if (ids.size > 0) {
      localStorage.setItem(KEY_PREFIX + path, JSON.stringify([...ids]));
    } else {
      // Empty ⇒ drop the key entirely, so a project with nothing hidden leaves
      // no trace (mirrors how project.yaml settings pop an emptied block).
      localStorage.removeItem(KEY_PREFIX + path);
    }
  } catch {
    // Storage disabled / quota — curation just won't persist; not fatal.
  }
}

// App calls this whenever the open project changes (with null on close). Loads
// that project's curated set into the reactive store.
export function openProjectHidden(path: string | null): void {
  currentPath = path;
  store.set(path ? readFromStorage(path) : new Set());
}

export function hideLibraryEntry(id: string): void {
  if (!currentPath) return;
  const next = readFromStorage(currentPath);
  if (next.has(id)) return;
  next.add(id);
  writeToStorage(currentPath, next);
  store.set(next);
}

export function unhideLibraryEntry(id: string): void {
  if (!currentPath) return;
  const next = readFromStorage(currentPath);
  if (!next.delete(id)) return;
  writeToStorage(currentPath, next);
  store.set(next);
}
