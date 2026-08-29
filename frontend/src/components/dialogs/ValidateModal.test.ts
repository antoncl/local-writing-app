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
  code_fenced_bodies: [],
};
const withIssues: ProjectValidation = {
  valid: false,
  errors: ["Scene 3 missing from structure"],
  warnings: ["TODO link dangles"],
  migrations_applied: [],
  code_fenced_bodies: [],
};
const withCodeFence: ProjectValidation = {
  valid: true,
  errors: [],
  warnings: [],
  migrations_applied: [],
  code_fenced_bodies: [{ id: "lore-shell", kind: "lore", title: "Shell" }],
};

const base = {
  open: true,
  onClose: () => {},
  checking: false,
  onRepair: () => {},
  onUnwrap: () => {},
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

  it("lists a whole-body code-fenced entry and unwraps it on click", async () => {
    const onUnwrap = vi.fn();
    render(ValidateModal, { props: { ...base, validation: withCodeFence, onUnwrap } });

    expect(screen.getByText("Bodies wrapped in a code block")).toBeTruthy();
    expect(screen.getByText("Shell")).toBeTruthy();
    // Advisory, not a structural error, so no Repair action is offered for it.
    expect(screen.queryByRole("button", { name: "Repair TODO Links" })).toBeNull();
    // And it is not mistaken for a clean project.
    expect(
      screen.queryByText("No structure, scene, or TODO synchronization issues found."),
    ).toBeNull();

    await fireEvent.click(screen.getByRole("button", { name: "Unwrap…" }));
    expect(onUnwrap).toHaveBeenCalledTimes(1);
    expect(onUnwrap).toHaveBeenCalledWith(withCodeFence.code_fenced_bodies[0]);
  });

  it("hides the results, and the Unwrap action, while a check is in flight", () => {
    render(ValidateModal, { props: { ...base, validation: withCodeFence, checking: true } });
    // The body shows the spinner, not stale results — so no Unwrap can fire
    // against a result that is being recomputed.
    expect(screen.getByText("Checking project files…")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Unwrap…" })).toBeNull();
  });

  it("closes via the Close button", async () => {
    const onClose = vi.fn();
    render(ValidateModal, { props: { ...base, onClose, validation: clean } });
    await fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
