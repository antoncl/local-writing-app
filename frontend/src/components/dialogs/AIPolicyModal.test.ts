// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";

// The modal drives the aiSettings singleton: it seeds a local draft from
// `policy` on open and, only on Save, commits the draft back and calls `save()`.
// Mock the singleton so we can assert the fails-closed contract (a radio click
// alone never persists) without a backend.
const mock = vi.hoisted(() => ({
  aiSettings: { policy: "off" as string, save: vi.fn() },
}));
vi.mock("@/lib/stores/aiSettings.svelte", () => ({ aiSettings: mock.aiSettings }));

import AIPolicyModal from "@/components/dialogs/AIPolicyModal.svelte";

const radio = (name: string) =>
  screen.getByRole("radio", { name }) as HTMLInputElement;

beforeEach(() => {
  mock.aiSettings.policy = "off";
  mock.aiSettings.save.mockReset();
  mock.aiSettings.save.mockResolvedValue(true); // persist succeeds by default
});

describe("AIPolicyModal", () => {
  it("renders nothing while closed", () => {
    render(AIPolicyModal, { props: { open: false, onClose: () => {} } });
    expect(screen.queryByRole("radio")).toBeNull();
  });

  it("seeds the stored policy on open", () => {
    mock.aiSettings.policy = "cloud-allowed";
    render(AIPolicyModal, { props: { open: true, onClose: () => {} } });
    expect(radio("Cloud allowed").checked).toBe(true);
    expect(radio("Off").checked).toBe(false);
  });

  it("commits the draft and persists, then closes, only on a successful Save", async () => {
    const onClose = vi.fn();
    render(AIPolicyModal, { props: { open: true, onClose } });

    await fireEvent.click(radio("Cloud allowed"));
    expect(mock.aiSettings.save).not.toHaveBeenCalled(); // radio click alone never persists

    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(onClose).toHaveBeenCalledTimes(1)); // closes after persist lands
    expect(mock.aiSettings.policy).toBe("cloud-allowed"); // committed
    expect(mock.aiSettings.save).toHaveBeenCalledTimes(1); // persisted
  });

  it("stays open when the save fails — the change isn't silently lost", async () => {
    mock.aiSettings.save.mockResolvedValue(false); // persist reports failure
    const onClose = vi.fn();
    render(AIPolicyModal, { props: { open: true, onClose } });

    await fireEvent.click(radio("Cloud allowed"));
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await vi.waitFor(() => expect(mock.aiSettings.save).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve)); // let the awaited save settle
    expect(onClose).not.toHaveBeenCalled(); // modal stays open, not a false success
  });

  it("discards the draft on Cancel — fails closed", async () => {
    mock.aiSettings.policy = "local-only";
    const onClose = vi.fn();
    render(AIPolicyModal, { props: { open: true, onClose } });

    await fireEvent.click(radio("Cloud allowed")); // edit, then bail out
    await fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(mock.aiSettings.save).not.toHaveBeenCalled();
    expect(mock.aiSettings.policy).toBe("local-only"); // controller untouched
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
