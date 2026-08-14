// @vitest-environment happy-dom
// The confirm service's resolution paths (#14; onCancel added for S6b's realize-undo
// abort). A caller that wraps `request` in a Promise needs a definitive outcome on
// every exit: confirm → onConfirm, cancel/backdrop → onCancel, suppressed → onConfirm
// immediately. happy-dom for localStorage (the suppression store).
import { afterEach, describe, expect, it } from "vitest";
import { confirmService } from "./confirmService.svelte";

afterEach(() => {
  confirmService.dismiss();
  try {
    localStorage.clear();
  } catch {
    // ignore
  }
});

describe("confirmService resolution", () => {
  it("runs onConfirm on resolve()", async () => {
    let confirmed = false;
    confirmService.request({
      title: "T",
      message: "M",
      confirmLabel: "Go",
      destructive: true,
      onConfirm: async () => {
        confirmed = true;
      },
    });
    await confirmService.resolve();
    expect(confirmed).toBe(true);
    expect(confirmService.active).toBe(null);
  });

  it("fires onCancel (not onConfirm) on dismiss() — the definitive 'declined'", () => {
    let confirmed = false;
    let cancelled = false;
    confirmService.request({
      title: "T",
      message: "M",
      confirmLabel: "Delete scene",
      destructive: true,
      onConfirm: async () => {
        confirmed = true;
      },
      onCancel: () => {
        cancelled = true;
      },
    });
    confirmService.dismiss();
    expect(cancelled).toBe(true);
    expect(confirmed).toBe(false);
    expect(confirmService.active).toBe(null);
  });

  it("a suppressed request runs onConfirm immediately and never opens the modal", async () => {
    localStorage.setItem("confirmSuppress:plot-realize-undo-delete-scene", "1");
    let confirmed = false;
    let cancelled = false;
    confirmService.request({
      title: "T",
      message: "M",
      confirmLabel: "Delete scene",
      destructive: true,
      dontShowAgainKey: "plot-realize-undo-delete-scene",
      onConfirm: async () => {
        confirmed = true;
      },
      onCancel: () => {
        cancelled = true;
      },
    });
    // Suppressed path resolves as a confirm without a modal; give the microtask a turn.
    await Promise.resolve();
    expect(confirmService.active).toBe(null);
    expect(confirmed).toBe(true);
    expect(cancelled).toBe(false);
  });
});
