// @vitest-environment happy-dom
/**
 * A pane intent aimed at a pane the same gesture is still creating (ADR-0090
 * Amendment 2 §2): the park must wait for BOTH the pane's document to land
 * and its NodeEditor handle to register — a single zero-delay retry missed
 * the handle in the real browser. The intent polls briefly, applies once,
 * and gives up silently.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createEmptyEditorPane } from "@/lib/editor-core/editorPaneModel";
import { editorPanes } from "./editorPanes.svelte";

function handle() {
  return {
    highlightEmbeddedTodo: vi.fn(),
    revealSearchMatch: vi.fn(),
    reloadScene: vi.fn(),
    tryMergeProse: vi.fn(),
    parkSnapshot: vi.fn(),
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  editorPanes.panes = [];
  editorPanes.editorPaneComponents = {};
});

afterEach(() => {
  vi.useRealTimers();
});

describe("pane intents wait for the pane's handle", () => {
  it("parks the source once the pane and its handle both exist", () => {
    editorPanes.parkSnapshotInOpenPane("lore_1", "snap_1");
    // Nothing yet: no pane at all.
    vi.advanceTimersByTime(250);
    editorPanes.panes = [{ ...createEmptyEditorPane("p1"), document: { type: "lore", id: "lore_1" } }];
    // The pane exists but its NodeEditor has not registered a handle.
    vi.advanceTimersByTime(250);
    const h = handle();
    editorPanes.editorPaneComponents = { p1: h as never };
    vi.advanceTimersByTime(250);
    expect(h.parkSnapshot).toHaveBeenCalledTimes(1);
    expect(h.parkSnapshot).toHaveBeenCalledWith("snap_1");
    // Applied once — later ticks do not repeat it.
    vi.advanceTimersByTime(2000);
    expect(h.parkSnapshot).toHaveBeenCalledTimes(1);
  });

  it("gives up silently when the pane never appears in time", () => {
    const h = handle();
    editorPanes.parkSnapshotInOpenPane("lore_missing", "snap_1");
    vi.advanceTimersByTime(10_000);
    editorPanes.panes = [{ ...createEmptyEditorPane("p3"), document: { type: "lore", id: "lore_missing" } }];
    editorPanes.editorPaneComponents = { p3: h as never };
    vi.advanceTimersByTime(1000);
    expect(h.parkSnapshot).not.toHaveBeenCalled();
  });
});
