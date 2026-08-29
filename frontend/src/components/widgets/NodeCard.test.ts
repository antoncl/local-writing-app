// @vitest-environment happy-dom
// NodeCard render contract (#1604). NodeCard's slots (leading / trailing / body)
// are exercised through a real consumer in Todo.test.ts; this covers the
// prop-driven chrome NodeCard owns itself — header text, the kind-stripe, and
// the active frame.
import { describe, it, expect } from "vitest";
import { render } from "@/lib/test/component";
import NodeCard from "@/components/widgets/NodeCard.svelte";

describe("NodeCard chrome", () => {
  it("renders the header title and detail", () => {
    const { container } = render(NodeCard, {
      props: { title: "Arrival — Act I", detail: "fix the sunrise timing" },
    });
    const text = container.querySelector(".node-card-text");
    expect(text?.querySelector("strong")?.textContent).toBe("Arrival — Act I");
    expect(text?.querySelector("small")?.textContent).toBe("fix the sunrise timing");
  });

  it("paints the kind-stripe from stripeColor", () => {
    const { container } = render(NodeCard, {
      props: { title: "T", stripeColor: "var(--star)" },
    });
    const card = container.querySelector(".node-card");
    expect(card?.classList.contains("has-row-stripe")).toBe(true);
    expect(card?.getAttribute("style") ?? "").toContain("--row-stripe: var(--star)");
  });

  it("stays stripe-less when no stripeColor is passed", () => {
    const { container } = render(NodeCard, { props: { title: "T" } });
    const card = container.querySelector(".node-card");
    expect(card?.classList.contains("has-row-stripe")).toBe(false);
    expect(card?.getAttribute("style") ?? "").toBe("");
  });

  it("carries the active frame only when active", () => {
    const off = render(NodeCard, { props: { title: "T" } });
    expect(off.container.querySelector(".node-card")?.classList.contains("active")).toBe(false);

    const on = render(NodeCard, { props: { title: "T", active: true } });
    expect(on.container.querySelector(".node-card")?.classList.contains("active")).toBe(true);
  });
});
