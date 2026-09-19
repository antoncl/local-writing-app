// @vitest-environment happy-dom
// paneViews (#2039): a selection KEY is a pane kind or a list tab's surface
// key `list:<entry_type>:<field_id>`. Pins the surface-key contract: the
// selected spec resolves under the key (null = the surface's own default), and
// a persisted surface-key selection survives `loadForProject` when the view is
// in ANY kind's roster (the key carries no kind) and drops when it is gone.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ api: { listViews: vi.fn() } }));
import { api } from "@/lib/api";
import { listTabSelectionKey, paneViews } from "@/lib/stores/paneViews.svelte";
import type { ViewNodeSummary } from "@/lib/types";

const CHARACTERS_SPEC = { kind: "lore", expr: { descendants_of: "lore:character" }, sort: { by: "title" } };
const VIEW: ViewNodeSummary = {
  id: "view_chars",
  title: "Characters A–Z",
  view_kind: "lore",
  spec: CHARACTERS_SPEC,
} as unknown as ViewNodeSummary;

const KEY = listTabSelectionKey("manuscript:scene", "characters");

beforeEach(() => {
  localStorage.clear();
  paneViews.reset();
  vi.mocked(api.listViews).mockResolvedValue({ entries: [VIEW] } as never);
});

afterEach(() => {
  paneViews.reset();
  localStorage.clear();
});

describe("paneViews surface keys (#2039)", () => {
  it("builds the key from entry type and field id", () => {
    expect(KEY).toBe("list:manuscript:scene:characters");
  });

  it("selectedSpec is null under a key with no selection, and the pane's kind key is untouched by a list-tab choice", async () => {
    await paneViews.loadForProject("/p");
    expect(paneViews.selectedSpec(KEY, "lore")).toBeNull();
    paneViews.select(KEY, "view_chars");
    expect(paneViews.selectedSpec(KEY, "lore")).toEqual(CHARACTERS_SPEC);
    expect(paneViews.selectedId("lore")).toBeNull();
    expect(paneViews.specFor("lore")).not.toEqual(CHARACTERS_SPEC);
  });

  it("a persisted surface-key selection is restored when the view exists in the roster", async () => {
    localStorage.setItem("paneView.selected." + KEY, "view_chars");
    await paneViews.loadForProject("/p");
    expect(paneViews.selectedId(KEY)).toBe("view_chars");
  });

  it("a persisted surface-key selection whose view is gone drops back to the default", async () => {
    localStorage.setItem("paneView.selected." + KEY, "view_deleted");
    await paneViews.loadForProject("/p");
    expect(paneViews.selectedId(KEY)).toBeNull();
  });
});
