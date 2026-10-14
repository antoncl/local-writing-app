// @vitest-environment happy-dom
// EditorFooter (#2473 split of NodeEditor): the status line and the Line edit
// review bar row. The foot dock is covered by FootDock.test.ts; here it is gated
// off (`dockVisible: false`) so the snapshot/scrub controllers stay inert.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import EditorFooter from "./EditorFooter.svelte";

function props(over: Record<string, unknown> = {}) {
  return {
    snapshots: {} as never,
    scrub: {} as never,
    documentKind: "manuscript" as const,
    dockVisible: false,
    snapshotWritesLabel: null,
    stopEditable: false,
    lineEditReview: null,
    sceneTitle: "Opening",
    dirty: false,
    ...over,
  };
}

describe("EditorFooter", () => {
  it("reads the document state in the status line", async () => {
    const { container, rerender } = render(EditorFooter, { props: props() });
    const status = () => container.querySelector("footer.status")?.textContent?.trim();
    expect(status()).toBe("Loaded Opening");
    await rerender(props({ dirty: true }));
    expect(status()).toBe("Unsaved changes");
    await rerender(props({ sceneTitle: null }));
    expect(status()).toBe("No scene open");
  });

  it("renders the review bar only while line edits are pending, and routes its buttons", async () => {
    const controller = {
      lineEdits: null as { remaining: number; index: number } | null,
      meta: null,
      generating: false,
      acceptAllLineEdits: vi.fn(),
      rejectAllLineEdits: vi.fn(),
      retry: vi.fn(),
    };
    const { rerender } = render(EditorFooter, { props: props({ lineEditReview: controller }) });
    expect(screen.queryByTestId("line-edit-review-bar")).toBeNull();

    controller.lineEdits = { remaining: 2, index: 1 };
    await rerender(props({ lineEditReview: { ...controller } }));
    expect(screen.getByTestId("line-edit-count").textContent).toBe("Edit 1 of 2");

    await fireEvent.click(screen.getByRole("button", { name: /accept all/i }));
    expect(controller.acceptAllLineEdits).toHaveBeenCalled();
  });

  it("renders the note bar (not the edit bar) while lore-check notes are pending, and routes its buttons", async () => {
    const controller = {
      lineEdits: null,
      lineNotes: null as { remaining: number; index: number; checkedAgainst: { id: string; name: string }[] } | null,
      meta: null,
      generating: false,
      dismissAllLineNotes: vi.fn(),
      retry: vi.fn(),
    };
    const { rerender } = render(EditorFooter, { props: props({ lineEditReview: controller }) });
    expect(screen.queryByTestId("line-note-review-bar")).toBeNull();

    controller.lineNotes = { remaining: 2, index: 1, checkedAgainst: [{ id: "lore_1", name: "Mira" }] };
    await rerender(props({ lineEditReview: { ...controller } }));
    expect(screen.getByTestId("line-note-count").textContent).toBe("Note 1 of 2");
    expect(screen.getByTestId("line-note-checked").textContent).toContain("Mira");
    expect(screen.queryByTestId("line-edit-review-bar")).toBeNull();

    await fireEvent.click(screen.getByTestId("line-note-dismiss-all"));
    expect(controller.dismissAllLineNotes).toHaveBeenCalled();
    await fireEvent.click(screen.getByTestId("line-note-retry"));
    expect(controller.retry).toHaveBeenCalled();
  });
});
