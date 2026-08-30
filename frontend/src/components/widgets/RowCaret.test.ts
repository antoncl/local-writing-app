// @vitest-environment happy-dom
// RowCaret's gutter contract (ADR-0066 Amendment 1, refined #1697): a collapsible
// row shows a real caret button; a leaf reserves an empty gutter ONLY when
// `reserveGutter` is set — otherwise it renders nothing, so a flat leaf-only
// level reclaims the ~22px instead of paying it as dead left-gutter.
import { describe, expect, it } from "vitest";
import { render } from "@/lib/test/component";
import RowCaret from "./RowCaret.svelte";

describe("RowCaret — gutter reservation (#1697)", () => {
  it("renders a real caret button when collapsible", () => {
    const { container } = render(RowCaret, { props: { collapsible: true } });
    expect(container.querySelector(".row-caret")).not.toBeNull();
    expect(container.querySelector(".row-caret-gutter")).toBeNull();
  });

  it("reserves an empty gutter for a leaf by default (reserveGutter defaults true)", () => {
    const { container } = render(RowCaret, { props: { collapsible: false } });
    expect(container.querySelector(".row-caret-gutter")).not.toBeNull();
    expect(container.querySelector(".row-caret")).toBeNull();
  });

  it("renders nothing for a leaf when reserveGutter is false — the row reclaims the width", () => {
    const { container } = render(RowCaret, { props: { collapsible: false, reserveGutter: false } });
    expect(container.querySelector(".row-caret-gutter")).toBeNull();
    expect(container.querySelector(".row-caret")).toBeNull();
  });
});
