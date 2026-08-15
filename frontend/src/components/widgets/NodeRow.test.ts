// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import NodeRow from "@/components/widgets/NodeRow.svelte";

// NodeRow is the app's most-reused list atom, so a regression here is
// app-wide. These pin its render contract (title/detail/state/tags) and its
// one interaction (onClick) — the shape every later widget test can copy.
describe("NodeRow", () => {
  it("renders the title as <strong> and the detail as <small>", () => {
    render(NodeRow, { props: { title: "Chapter One", detail: "manuscript:chapter" } });
    expect(screen.getByText("Chapter One").tagName).toBe("STRONG");
    expect(screen.getByText("manuscript:chapter").tagName).toBe("SMALL");
  });

  it("applies the active class when active", () => {
    const { container } = render(NodeRow, { props: { title: "X", active: true } });
    expect(container.querySelector(".node-row")).toHaveClass("active");
  });

  it("exposes the node id as a data attribute", () => {
    const { container } = render(NodeRow, { props: { title: "X", dataNodeId: "abc123" } });
    expect(container.querySelector(".node-row")).toHaveAttribute("data-node-id", "abc123");
  });

  it("fires onClick when the row is clicked", async () => {
    const onClick = vi.fn();
    render(NodeRow, { props: { title: "Click me", onClick } });
    await fireEvent.click(screen.getByRole("button", { name: "Click me" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("renders a plain title (no button) when not clickable", () => {
    render(NodeRow, { props: { title: "Static", clickable: false } });
    expect(screen.queryByRole("button", { name: "Static" })).toBeNull();
    expect(screen.getByText("Static")).toBeInTheDocument();
  });

  it("caps visible tags at two and shows a +N overflow chip", () => {
    render(NodeRow, { props: { title: "T", tags: ["alpha", "beta", "gamma", "delta"] } });
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("beta")).toBeInTheDocument();
    expect(screen.queryByText("gamma")).toBeNull();
    expect(screen.getByText("+2")).toBeInTheDocument();
  });
});
