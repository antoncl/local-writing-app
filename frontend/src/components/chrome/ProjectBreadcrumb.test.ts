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
import type { ProjectChainLayer, ProjectChild } from "@/lib/types";
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

// The child projects inside the open one (#417 slice 5). "Chapter One" keeps its
// folder name as its title (nothing to disambiguate); "Sequel" has been renamed,
// so its folder name is worth showing.
const CHILDREN: ProjectChild[] = [
  { path: "/w/book/chapter-one", name: "Chapter One", title: "Chapter One" },
  { path: "/w/book/sequel", name: "sequel-draft", title: "Sequel" },
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
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();

    // It's a modal dialog that owns focus: aria wiring + focus lands inside it
    // (on the first enabled row), not on the trigger behind the overlay.
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(edit.getAttribute("aria-controls")).toBe("inherit-popover");
    expect(dialog.contains(document.activeElement)).toBe(true);

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

  it("keeps Tab focus inside the open dialog", async () => {
    render(ProjectBreadcrumb, { props: { chain: CHAIN, inheritRows: ROWS } });
    await fireEvent.click(screen.getByRole("button", { name: "Edit what this project inherits from" }));

    // The disabled folder row is skipped, so the trap cycles the two enabled
    // rows: first = Universe, last = Series.
    const first = screen.getByRole("checkbox", { name: "Inherit from Universe" });
    const last = screen.getByRole("checkbox", { name: "Inherit from Series" });
    expect(document.activeElement).toBe(first); // initial focus landed inside

    // Tab off the last wraps to the first; Shift+Tab off the first wraps to last.
    last.focus();
    await fireEvent.keyDown(window, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    await fireEvent.keyDown(window, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
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

  it("withholds the edit affordance when the only enumerated row is a disabled folder", () => {
    // A project directly inside the machine root enumerates that root as a single
    // NON-toggleable `folder` row — present, but nothing to declare. The edit
    // affordance must still be withheld: it must never open onto an all-disabled
    // list (#427). The `inheritRows: []` case above can't prove this — it pins the
    // EMPTY enumeration; this pins that a present-but-untoggleable row is equally
    // "nothing to edit" (#766.2, restoring the dropped `canDeclareInheritance`
    // unit case that a `canDeclare = inheritRows.some(r => r.toggleable)` regression
    // would slip past).
    render(ProjectBreadcrumb, {
      props: { chain: CHAIN, inheritRows: [row("writing", { state: "folder", toggleable: false })] },
    });
    expect(
      screen.queryByRole("button", { name: "Edit what this project inherits from" }),
    ).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("ProjectBreadcrumb — descent menu (#417 slice 5)", () => {
  it("hides the descent affordance when the project has no children", () => {
    render(ProjectBreadcrumb, { props: { chain: CHAIN, childProjects: [] } });
    expect(screen.queryByRole("button", { name: "Contains" })).toBeNull();
  });

  it("opens the menu, lists the children (folder name only when it differs), and opens one via onOpen", async () => {
    // Children reuse the crumb `onOpen` callback — a child is just another
    // project path to open (a scope change), so no separate handler is threaded.
    const onOpen = vi.fn();
    render(ProjectBreadcrumb, { props: { chain: CHAIN, childProjects: CHILDREN, onOpen } });

    // Closed to start: the chevron is collapsed, no menu.
    const descend = screen.getByRole("button", { name: "Contains" });
    expect(descend.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("menu", { name: "Projects inside this one" })).toBeNull();

    await fireEvent.click(descend);
    expect(descend.getAttribute("aria-expanded")).toBe("true");
    const menu = screen.getByRole("menu", { name: "Projects inside this one" });
    expect(menu).toBeInTheDocument();

    // It is a non-modal navigation menu, not the inheritance dialog.
    expect(screen.queryByRole("dialog")).toBeNull();

    // Both children render as menuitems. The accessible name is a clean
    // "Open <title>" (aria-label), so a screen reader never reads the folder
    // slug as part of the name — but the slug still renders VISIBLY for the
    // renamed one, and the same-named one prints no duplicate line.
    const one = screen.getByRole("menuitem", { name: "Open Chapter One" });
    const sequel = screen.getByRole("menuitem", { name: "Open Sequel" });
    expect(one).toBeInTheDocument();
    expect(sequel.textContent).toContain("sequel-draft"); // folder shown visibly
    expect(sequel.getAttribute("aria-label")).toBe("Open Sequel"); // but not in the a11y name
    expect(one.textContent).not.toContain("Chapter One Chapter One");

    // Opening a child routes through onOpen with its path and closes the menu.
    await fireEvent.click(sequel);
    expect(onOpen).toHaveBeenCalledWith("/w/book/sequel");
    expect(screen.queryByRole("menu", { name: "Projects inside this one" })).toBeNull();
  });

  it("closes on Escape (refocusing the chevron) and on an outside click", async () => {
    render(ProjectBreadcrumb, { props: { chain: CHAIN, childProjects: CHILDREN } });
    const descend = screen.getByRole("button", { name: "Contains" });

    await fireEvent.click(descend);
    expect(screen.queryByRole("menu")).toBeInTheDocument();
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(descend);

    // Reopen, then dismiss by clicking the overlay (no refocus).
    await fireEvent.click(descend);
    expect(screen.queryByRole("menu")).toBeInTheDocument();
    await fireEvent.click(document.querySelector(".popover-overlay")!);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("shows descent on a flat project that still contains children", async () => {
    // No ancestors → the "Inherits from nothing" note branch — but a top-level
    // project can still contain child projects, so the chevron rides that branch.
    render(ProjectBreadcrumb, {
      props: { chain: [layer("book", { is_root: true })], inheritRows: [], childProjects: CHILDREN },
    });
    expect(screen.getByText("Inherits from nothing")).toBeInTheDocument();
    const descend = screen.getByRole("button", { name: "Contains" });
    await fireEvent.click(descend);
    expect(screen.getByRole("menu", { name: "Projects inside this one" })).toBeInTheDocument();
  });

  it("never opens both bar popovers at once", async () => {
    // The inherit dialog and the descent menu are mutually exclusive: opening one
    // closes the other, so their shared overlay can't stack.
    render(ProjectBreadcrumb, { props: { chain: CHAIN, inheritRows: ROWS, childProjects: CHILDREN } });

    await fireEvent.click(screen.getByRole("button", { name: "Edit what this project inherits from" }));
    expect(screen.queryByRole("dialog")).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("button", { name: "Contains" }));
    expect(screen.queryByRole("menu", { name: "Projects inside this one" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();

    // And back the other way.
    await fireEvent.click(screen.getByRole("button", { name: "Edit what this project inherits from" }));
    expect(screen.queryByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByRole("menu", { name: "Projects inside this one" })).toBeNull();
  });
});
