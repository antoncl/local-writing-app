// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import ValidateModal from "@/components/dialogs/ValidateModal.svelte";
import type { ProjectValidation } from "@/lib/types";

const clean: ProjectValidation = {
  valid: true,
  errors: [],
  warnings: [],
  migrations_applied: [],
};
const withIssues: ProjectValidation = {
  valid: false,
  errors: ["Scene 3 missing from structure"],
  warnings: ["TODO link dangles"],
  migrations_applied: [],
};

const base = {
  open: true,
  onClose: () => {},
  checking: false,
  onRepair: () => {},
};

describe("ValidateModal", () => {
  it("renders nothing while closed", () => {
    render(ValidateModal, { props: { ...base, open: false, validation: clean } });
    expect(screen.queryByText("Project looks consistent")).toBeNull();
  });

  it("shows a checking state and no results while validating", () => {
    render(ValidateModal, { props: { ...base, checking: true, validation: null } });
    expect(screen.getByText("Checking project files…")).toBeTruthy();
    // The stale prior result must not flash under the spinner.
    expect(screen.queryByText("Project looks consistent")).toBeNull();
    expect(screen.queryByRole("button", { name: "Repair TODO Links" })).toBeNull();
  });

  it("reports a clean project with no Repair action", () => {
    render(ValidateModal, { props: { ...base, validation: clean } });
    expect(screen.getByText("Project looks consistent")).toBeTruthy();
    expect(
      screen.getByText("No structure, scene, or TODO synchronization issues found."),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Repair TODO Links" })).toBeNull();
  });

  it("disables Repair while a check/repair is in flight", () => {
    render(ValidateModal, { props: { ...base, validation: withIssues, checking: true } });
    // Footer stays rendered off the pre-run result, but Repair must not fire a
    // concurrent repair while checking.
    expect(
      (screen.getByRole("button", { name: "Repair TODO Links" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("lists errors and warnings and offers Repair when there are issues", async () => {
    const onRepair = vi.fn();
    render(ValidateModal, { props: { ...base, validation: withIssues, onRepair } });

    expect(screen.getByText("Project issues found")).toBeTruthy();
    expect(screen.getByText("Scene 3 missing from structure")).toBeTruthy();
    expect(screen.getByText("TODO link dangles")).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: "Repair TODO Links" }));
    expect(onRepair).toHaveBeenCalledTimes(1);
  });

  it("closes via the Close button", async () => {
    const onClose = vi.fn();
    render(ValidateModal, { props: { ...base, onClose, validation: clean } });
    await fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
