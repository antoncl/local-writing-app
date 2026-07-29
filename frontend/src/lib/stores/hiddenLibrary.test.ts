// @vitest-environment happy-dom
// Per-project Library hide (ADR-0049 slice 3, #680). Pins the localStorage
// contract: hide/unhide mutate the reactive set AND persist, curation is keyed
// per project, an emptied set drops its key (fresh-project form), the set
// round-trips a re-open, and corrupt/absent storage reads as "nothing hidden".
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { get } from "svelte/store";
import {
  hiddenLibraryStore,
  hideLibraryEntry,
  openProjectHidden,
  unhideLibraryEntry,
} from "./hiddenLibrary";

const A = "C:/projects/alpha";
const B = "C:/projects/beta";
const keyFor = (path: string) => "libraryHidden:" + path;

beforeEach(() => {
  localStorage.clear();
  // The store is a singleton with module-level current-project state — reset it
  // between tests so one test's open project doesn't leak into the next.
  openProjectHidden(null);
});
afterEach(() => localStorage.clear());

describe("hiddenLibrary (ADR-0049 slice 3)", () => {
  it("hide adds to the reactive set and persists to localStorage", () => {
    openProjectHidden(A);
    expect([...get(hiddenLibraryStore)]).toEqual([]);
    hideLibraryEntry("builtin-roleplay");
    expect(get(hiddenLibraryStore).has("builtin-roleplay")).toBe(true);
    expect(localStorage.getItem(keyFor(A))).toBe(JSON.stringify(["builtin-roleplay"]));
  });

  it("unhide removes it and drops the key when the set empties", () => {
    openProjectHidden(A);
    hideLibraryEntry("x");
    unhideLibraryEntry("x");
    expect(get(hiddenLibraryStore).has("x")).toBe(false);
    expect(localStorage.getItem(keyFor(A))).toBeNull();
  });

  it("curation is per-project — hiding in one project does not touch another", () => {
    openProjectHidden(A);
    hideLibraryEntry("x");
    openProjectHidden(B);
    expect(get(hiddenLibraryStore).has("x")).toBe(false);
    hideLibraryEntry("y");
    openProjectHidden(A);
    expect([...get(hiddenLibraryStore)]).toEqual(["x"]);
  });

  it("survives a re-open — the set round-trips through localStorage", () => {
    openProjectHidden(A);
    hideLibraryEntry("x");
    openProjectHidden(null);
    openProjectHidden(A);
    expect(get(hiddenLibraryStore).has("x")).toBe(true);
  });

  it("hide is inert with no project open", () => {
    openProjectHidden(null);
    hideLibraryEntry("x");
    expect(get(hiddenLibraryStore).size).toBe(0);
  });

  it("corrupt storage reads as nothing hidden", () => {
    localStorage.setItem(keyFor(A), "{not json");
    openProjectHidden(A);
    expect(get(hiddenLibraryStore).size).toBe(0);
  });
});
