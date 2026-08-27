// @vitest-environment happy-dom
// The one rail section header (#1438). Locks its contract: the disclosure
// toggle fires, the glyph class is rendered, and the count pill shows only when
// a count is given — the three rail panels (References / Conversations / Staged
// changes) all render through this, so a regression here breaks all three.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import RailSectionHeader from "./RailSectionHeader.svelte";

describe("RailSectionHeader", () => {
  it("renders the title, glyph class, and count pill", () => {
    const { container } = render(RailSectionHeader, {
      props: { title: "References", glyph: "ti-link", count: 3, expanded: false, onToggle: () => {} },
    });
    expect(screen.getByText("References")).toBeInTheDocument();
    expect(container.querySelector("i.ti.ti-link")).not.toBeNull();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("omits the count pill when no count is given", () => {
    render(RailSectionHeader, {
      props: { title: "Conversations", glyph: "ti-messages", count: null, expanded: true, onToggle: () => {} },
    });
    // The title button carries no numeric pill (a bare header, count-free).
    expect(screen.queryByText(/^\d+$/)).toBeNull();
  });

  it("fires onToggle when the disclosure button is clicked", async () => {
    const onToggle = vi.fn();
    render(RailSectionHeader, {
      props: { title: "Staged changes", glyph: "ti-stack-2", count: 0, expanded: false, onToggle },
    });
    await fireEvent.click(screen.getByRole("button", { name: /Staged changes/ }));
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("reflects expanded state on the toggle for assistive tech", () => {
    render(RailSectionHeader, {
      props: { title: "References", glyph: "ti-link", count: 0, expanded: true, onToggle: () => {} },
    });
    expect(screen.getByRole("button", { name: /References/ })).toHaveAttribute("aria-expanded", "true");
  });
});
