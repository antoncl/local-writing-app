// @vitest-environment happy-dom
// #867 — a built-in *extra* view (e.g. "Openable chats") is frontend-synthesized,
// not a backend `view:view` node, so `paneViews` has to treat its id as a valid
// selection even though `listViews()` never returns it. This pins that wiring —
// the view-layer blind spot the harness memo names — so a regression in
// `storedSelectionKinds` / the restore validity check / the reload drop-loop /
// the `specFor` fallback can't silently revert a user's Openable selection to
// "All chats" while every other test stays green.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { paneViews } from "./paneViews.svelte";
import { api } from "@/lib/api";
import type { MetadataSchema } from "@/lib/types";

const CHAT_SCHEMA = {
  entry_types: { "chat:chat_session": { name: "Chat", kind: "chat" } },
  fields: {},
} as unknown as MetadataSchema;

const OPENABLE_ID = "view_builtin_chat_openable";
const KEY = "paneView.selected.chat";

beforeEach(() => {
  localStorage.clear();
  paneViews.reset();
  // No saved chat views on the backend — the Openable selection must still restore.
  vi.spyOn(api, "listViews").mockResolvedValue({ entries: [] });
});
afterEach(() => {
  localStorage.clear();
  paneViews.reset();
  vi.restoreAllMocks();
});

describe("paneViews — built-in extra selection (#867)", () => {
  it("restores an Openable selection on load with no saved chat views", async () => {
    localStorage.setItem(KEY, OPENABLE_ID);
    await paneViews.loadForProject("/proj");
    expect(paneViews.selectedId("chat")).toBe(OPENABLE_ID);
    // …and resolves to the openable spec (its predicate filters seed_committing).
    const spec = paneViews.specFor("chat", CHAT_SCHEMA);
    expect(spec.expr?.filter?.pred?.field?.key).toBe("seed_committing");
    expect(spec.expr?.filter?.pred?.field?.op).toBe("disjoint");
  });

  it("keeps the built-in extra selection across a reload", async () => {
    localStorage.setItem(KEY, OPENABLE_ID);
    await paneViews.loadForProject("/proj");
    // A reload (e.g. after a view edit) must not drop it just because the backend
    // roster doesn't contain it.
    await paneViews.reload();
    expect(paneViews.selectedId("chat")).toBe(OPENABLE_ID);
  });

  it("drops a stale non-built-in selection that no longer resolves", async () => {
    localStorage.setItem(KEY, "view_deleted0000");
    await paneViews.loadForProject("/proj");
    expect(paneViews.selectedId("chat")).toBeNull();
    // …falling back to the default (roster) spec.
    expect(paneViews.specFor("chat", CHAT_SCHEMA).expr?.descendants_of).toBe("chat:chat_session");
  });
});
