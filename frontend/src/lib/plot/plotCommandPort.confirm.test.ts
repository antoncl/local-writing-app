// @vitest-environment happy-dom
// The real `confirmSceneDelete` glue (S6b): defaultPlotCommandPort wraps the
// callback-based confirmService into a Promise<boolean> for the realize-undo abort.
// The fake port used elsewhere bypasses this composition, so pin it directly — a
// dropped onCancel would hang a live realize-undo (the caretaker stays #replaying).
// happy-dom for confirmService's localStorage suppression store.
import { afterEach, describe, expect, it } from "vitest";
import { defaultPlotCommandPort } from "./plotCommands";
import { confirmService } from "@/lib/stores/confirmService.svelte";

afterEach(() => {
  confirmService.dismiss();
  try {
    localStorage.clear();
  } catch {
    // ignore
  }
});

describe("defaultPlotCommandPort().confirmSceneDelete", () => {
  it("opens the modal and resolves true when confirmed", async () => {
    const pending = defaultPlotCommandPort().confirmSceneDelete({ title: "The letter", body: "prose" });
    expect(confirmService.active).not.toBe(null); // a real modal, not silently resolved
    await confirmService.resolve();
    expect(await pending).toBe(true);
  });

  it("resolves false when cancelled/dismissed — the definitive abort signal", async () => {
    const pending = defaultPlotCommandPort().confirmSceneDelete({ title: "The letter", body: "prose" });
    confirmService.dismiss();
    expect(await pending).toBe(false);
  });

  it("resolves true immediately (no modal) once the writer suppressed the confirm", async () => {
    localStorage.setItem("confirmSuppress:plot-realize-undo-delete-scene", "1");
    const pending = defaultPlotCommandPort().confirmSceneDelete({ title: "The letter", body: "prose" });
    expect(confirmService.active).toBe(null); // suppressed → no modal
    expect(await pending).toBe(true);
  });
});
