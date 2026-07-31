// @vitest-environment happy-dom
// TopBar had no test (the gap #766.1 called out): the project switcher and the ≡
// app menu are two hand-rolled popovers now rewired onto the shared `<Popover>`
// primitive, and the rewire has to preserve their NON-modal dismiss contract —
// open/close, Escape refocuses the trigger, an overlay click dismisses without
// refocus, and (unlike the breadcrumb's modal inherit dialog) focus is NOT pulled
// into the panel. This pins that contract on both menus, plus the one bit of
// per-menu wiring the primitive can't own: the app menu resetting its inline
// "save preset" field on any dismiss (the `onClose` hook). The breadcrumb's own
// test already covers the modal path through the same primitive.
import { describe, it, expect, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent } from "@/lib/test/component";
import TopBar from "./TopBar.svelte";
import type { RecentProject } from "@/lib/types";

const RECENTS: RecentProject[] = [
  { path: "/w/one", title: "One", opened_at: "2026-07-30T10:00:00Z", within_root: true },
  { path: "/w/two", title: "Two", opened_at: "2026-07-30T09:00:00Z", within_root: true },
];

describe("TopBar — project switcher (#766.1)", () => {
  it("opens on the trigger, lists recents, and routes a selection through the host", async () => {
    const onSelectRecent = vi.fn();
    render(TopBar, { props: { currentTitle: "My Book", recentProjects: RECENTS, onSelectRecent } });

    const trigger = screen.getByRole("button", { name: "My Book" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("menu", { name: "Project switcher" })).toBeNull();

    await fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("menu", { name: "Project switcher" })).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("menuitem", { name: /One/ }));
    expect(onSelectRecent).toHaveBeenCalledWith("/w/one");
    // Selecting navigates, so the menu closes.
    expect(screen.queryByRole("menu", { name: "Project switcher" })).toBeNull();
  });

  it("is non-modal: opening does not pull focus off the trigger", async () => {
    render(TopBar, { props: { currentTitle: "My Book", recentProjects: RECENTS } });
    const trigger = screen.getByRole("button", { name: "My Book" });

    trigger.focus();
    await fireEvent.click(trigger);
    const menu = screen.getByRole("menu", { name: "Project switcher" });
    // A menu, not a dialog, and focus stayed on the trigger — the panel never
    // steals it (contrast the breadcrumb's modal inherit dialog).
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(menu.contains(document.activeElement)).toBe(false);
    expect(document.activeElement).toBe(trigger);
  });

  it("closes on Escape (refocusing the trigger) and on an outside click", async () => {
    render(TopBar, { props: { currentTitle: "My Book", recentProjects: RECENTS } });
    const trigger = screen.getByRole("button", { name: "My Book" });

    await fireEvent.click(trigger);
    expect(screen.queryByRole("menu", { name: "Project switcher" })).toBeInTheDocument();
    await fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("menu", { name: "Project switcher" })).toBeNull();
    expect(document.activeElement).toBe(trigger);

    // Reopen, then dismiss by clicking the overlay — no refocus for a mouse user.
    await fireEvent.click(trigger);
    expect(screen.queryByRole("menu", { name: "Project switcher" })).toBeInTheDocument();
    await fireEvent.click(document.querySelector(".popover-overlay")!);
    expect(screen.queryByRole("menu", { name: "Project switcher" })).toBeNull();
  });

  it("clears a stale recent, keeping the menu open and focus inside it via bind:panel (#423)", async () => {
    // The host callback here does NOT drop the row (a plain spy), so after the
    // click both ×-buttons still exist. handleRemoveRecent then lands focus on the
    // button that slid into the vacated slot — with no removal that is the SAME ×
    // (index 0). That focus juggle reads `.recent-remove` out of the panel the
    // primitive hands back through `bind:panel`; a broken binding leaves
    // switcherMenuEl null and falls through to focusing the switcher TOGGLE, which
    // this pins against (the one genuinely novel wiring in the #766.1 rewire).
    const onRemoveRecent = vi.fn();
    render(TopBar, { props: { currentTitle: "My Book", recentProjects: RECENTS, onRemoveRecent } });

    await fireEvent.click(screen.getByRole("button", { name: "My Book" }));
    const removeOne = screen.getByRole("button", { name: "Remove One from recent projects" });
    await fireEvent.click(removeOne);
    await tick(); // let handleRemoveRecent's await onRemoveRecent + await tick settle
    await tick();

    expect(onRemoveRecent).toHaveBeenCalledWith("/w/one");
    // Clearing dead rows is housekeeping, not navigation — the menu stays open.
    expect(screen.queryByRole("menu", { name: "Project switcher" })).toBeInTheDocument();
    // Focus stayed inside the panel (on the ×), not dropped to the switcher toggle.
    expect(document.activeElement).toBe(removeOne);
    expect(document.activeElement).not.toBe(screen.getByRole("button", { name: "My Book" }));
  });
});

describe("TopBar — app menu (#766.1)", () => {
  it("opens the ≡ menu and closes it on Escape, refocusing the trigger", async () => {
    render(TopBar, { props: { currentTitle: "My Book", projectOpen: true } });
    const trigger = screen.getByRole("button", { name: "Application menu" });

    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    await fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    const menu = screen.getByRole("menu", { name: "Application menu" });
    expect(menu).toBeInTheDocument();
    // Non-modal like the switcher: focus is not trapped inside.
    expect(screen.queryByRole("dialog")).toBeNull();

    await fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("menu", { name: "Application menu" })).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("fires a menu action through the host and closes", async () => {
    const onOpenSettings = vi.fn();
    render(TopBar, { props: { currentTitle: "My Book", projectOpen: true, onOpenSettings } });

    await fireEvent.click(screen.getByRole("button", { name: "Application menu" }));
    await fireEvent.click(screen.getByRole("menuitem", { name: /Settings/ }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
    expect(screen.queryByRole("menu", { name: "Application menu" })).toBeNull();
  });

  it("resets the inline save-preset field whenever the menu dismisses (onClose)", async () => {
    render(TopBar, { props: { currentTitle: "My Book", projectOpen: true } });

    // Reveal the "save current layout as…" input.
    await fireEvent.click(screen.getByRole("button", { name: "Application menu" }));
    await fireEvent.click(screen.getByRole("menuitem", { name: "Save current as…" }));
    expect(screen.getByRole("textbox", { name: "New preset name" })).toBeInTheDocument();

    // Dismiss via Escape — the primitive's onClose hook must reset the field.
    await fireEvent.keyDown(window, { key: "Escape" });
    // Reopen: the field is gone, the "Save current as…" affordance is back.
    await fireEvent.click(screen.getByRole("button", { name: "Application menu" }));
    expect(screen.queryByRole("textbox", { name: "New preset name" })).toBeNull();
    expect(screen.getByRole("menuitem", { name: "Save current as…" })).toBeInTheDocument();
  });
});
