// @vitest-environment happy-dom
// #417 slice 4: the breadcrumb doubles as the inheritance-state display
// (reversing #431). Slice 4b then moves the *editing* onto the bar too: the
// "edit…" affordance opens a popover hosting the declaration list, replacing the
// Project pane's Inheritance section. This pins both render contracts the
// `projectChain` unit test can't see — the crumb states, and that the popover
// opens, lists the enumerated rows, routes toggles through the host, and closes
// on Escape / outside-click (the #642 lesson: assert the DISPLAY, not just the
// pure helpers).
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import ProjectBreadcrumb from "./ProjectBreadcrumb.svelte";
import type { ProjectChainLayer } from "@/lib/types";
import type { DeclarationRow } from "@/lib/utils/projectChain";

function layer(name: string, overrides: Partial<ProjectChainLayer> = {}): ProjectChainLayer {
  return {
    id: `l-${name}`,
    label: name,
    path: `/w/${name}`,
    is_root: false,
    is_project: true,
    inherited: true,
    ...overrides,
  };
}

function row(label: string, overrides: Partial<DeclarationRow> = {}): DeclarationRow {
  return {
    path: `/w/${label}`,
    label,
    detail: null,
    state: "available",
    checked: false,
    toggleable: true,
    ...overrides,
  };
}

const CHAIN = [
  layer("universe", { label: "Universe" }), // declared
  layer("series", { label: "Series", inherited: false }), // available
  layer("gone", { label: "Gone", is_project: false, inherited: true }), // stale
  layer("book", { label: "Book", is_root: true }), // the open project (leaf)
];

// The enumeration behind that chain: the disabled projects-folder, the declared
// ancestor, an available one — i.e. at least one toggleable row, so the "edit…"
// affordance appears.
const ROWS = [
  row("writing", { state: "folder", toggleable: false }),
  row("Universe", { state: "declared", checked: true }),
  row("Series", { state: "available" }),
];

describe("ProjectBreadcrumb — inheritance state (#417 slice 4)", () => {
  it("draws declared solid, available dimmed+clickable, stale inert, each state announced", async () => {
    const onOpen = vi.fn();
    render(ProjectBreadcrumb, { props: { chain: CHAIN, onOpen } });

    // declared: a solid button, NOT dimmed, no state suffix on its name.
    const declared = screen.getByRole("button", { name: "Universe" });
    expect(declared.classList.contains("available")).toBe(false);

    // available: dimmed button whose accessible name announces "not inherited".
    const available = screen.getByRole("button", { name: "Series — not inherited" });
    expect(available.classList.contains("available")).toBe(true);

    // stale: NOT a button (nothing to open), a struck marker whose text
    // announces the broken state (getNodeText is the span's own "Gone").
    expect(screen.queryByRole("button", { name: /Gone/ })).toBeNull();
    const stale = screen.getByText("Gone");
    expect(stale.classList.contains("stale")).toBe(true);
    expect(stale.textContent).toContain("no longer a project");

    // the open project is the switcher's job, never a crumb.
    expect(screen.queryByText("Book")).toBeNull();

    // clicking a real project (dimmed or not) opens it; the stale marker can't.
    await fireEvent.click(available);
    await fireEvent.click(declared);
    await fireEvent.click(stale);
    expect(onOpen.mock.calls).toEqual([["/w/series"], ["/w/universe"]]);
  });
});

describe("ProjectBreadcrumb — inheritance popover (#417 slice 4b)", () => {
  it("opens the editor from the edit affordance and routes a toggle through the host", async () => {
    const onToggleInherit = vi.fn();
    render(ProjectBreadcrumb, { props: { chain: CHAIN, inheritRows: ROWS, onToggleInherit } });

    // Closed to start: the trigger is collapsed and there is no dialog.
    const edit = screen.getByRole("button", { name: "Edit what this project inherits from" });
    expect(edit.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("dialog")).toBeNull();

    await fireEvent.click(edit);
    expect(edit.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    // Every enumerated row renders, including the disabled organisational folder.
    const universe = screen.getByRole("checkbox", { name: "Inherit from Universe" });
    expect((universe as HTMLInputElement).checked).toBe(true);
    const writing = screen.getByRole("checkbox", { name: "Inherit from writing" });
    expect((writing as HTMLInputElement).disabled).toBe(true);

    // Ticking routes through the host, keyed by path — the list never trusts the
    // DOM checkbox (the save can fail).
    await fireEvent.click(screen.getByRole("checkbox", { name: "Inherit from Series" }));
    expect(onToggleInherit).toHaveBeenCalledWith("/w/Series");
  });

  it("locks the checkboxes while a declaration save is in flight", async () => {
    render(ProjectBreadcrumb, {
      props: { chain: CHAIN, inheritRows: ROWS, inheritSaving: true },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Edit what this project inherits from" }));

    // Even the toggleable rows are disabled mid-round-trip (#426).
    expect((screen.getByRole("checkbox", { name: "Inherit from Series" }) as HTMLInputElement).disabled).toBe(true);
  });

  it("closes on Escape (refocusing the trigger) and on an outside click", async () => {
    render(ProjectBreadcrumb, { props: { chain: CHAIN, inheritRows: ROWS } });
    const edit = screen.getByRole("button", { name: "Edit what this project inherits from" });

    await fireEvent.click(edit);
    expect(screen.queryByRole("dialog")).toBeInTheDocument();
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(edit);

    // Reopen, then dismiss by clicking the overlay.
    await fireEvent.click(edit);
    expect(screen.queryByRole("dialog")).toBeInTheDocument();
    await fireEvent.click(document.querySelector(".popover-overlay")!);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows a remedy-less note for a flat project with nothing to declare", () => {
    // Only the leaf → crumbs empty → the note. With no toggleable row the edit
    // affordance is withheld (it lives on the populated bar), and the popover is
    // unreachable — the note stands alone.
    render(ProjectBreadcrumb, {
      props: { chain: [layer("book", { is_root: true })], inheritRows: [] },
    });
    expect(screen.getByText("Inherits from nothing")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
