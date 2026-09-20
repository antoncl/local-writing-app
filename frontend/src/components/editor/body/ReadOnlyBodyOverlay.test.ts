// @vitest-environment happy-dom
// ReadOnlyBodyOverlay (#2054 / #2051): the overlay's content sits on the same
// `.prose-column` as the live editor, and the front matter / appendix blocks
// render around it in document order — so the facts stay with the document
// while a scrub or a parked snapshot replaces the body.
import { describe, expect, it } from "vitest";
import { createRawSnippet } from "svelte";
import { render } from "@/lib/test/component";
import ReadOnlyBodyOverlay from "./ReadOnlyBodyOverlay.svelte";

function block(text: string) {
  return createRawSnippet(() => ({ render: () => `<p class="blk-test">${text}</p>` }));
}

describe("ReadOnlyBodyOverlay", () => {
  it("renders the body alone on the prose column when no blocks are given", () => {
    render(ReadOnlyBodyOverlay, { props: { html: "<p>body</p>", label: "Effective body (read-only)" } });
    const content = document.querySelector(".effective-body-content");
    expect(content?.classList.contains("prose-column")).toBe(true);
    expect(document.querySelector('[data-testid="overlay-front-matter"]')).toBeNull();
    expect(document.querySelector('[data-testid="overlay-appendix"]')).toBeNull();
  });

  it("front matter precedes the body and the appendix follows it (#2054)", () => {
    render(ReadOnlyBodyOverlay, {
      props: {
        html: "<p>body</p>",
        label: "Snapshot body (read-only)",
        frontMatter: block("facts"),
        appendix: block("trailing"),
      },
    });
    const overlay = document.querySelector(".effective-body")!;
    const order = Array.from(overlay.children).map((el) => el.className.split(" ")[0]);
    expect(order).toEqual(["effective-front-matter", "effective-body-content", "effective-appendix"]);
    expect(document.querySelector('[data-testid="overlay-front-matter"]')?.classList.contains("prose-column")).toBe(true);
    expect(document.querySelector('[data-testid="overlay-appendix"]')?.textContent).toBe("trailing");
  });
});
