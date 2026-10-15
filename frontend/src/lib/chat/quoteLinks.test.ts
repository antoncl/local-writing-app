// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";
import { findQuote, linkQuotes, scenePlainText } from "./quoteLinks";

const SCENE = "She said “the lantern was still burning” — and then nothing more.\nA second block mentions rain on slate.";

describe("scenePlainText", () => {
  it("keeps paragraph text, joins blocks with newlines, drops HTML comments", async () => {
    const plain = await scenePlainText("First paragraph here.\n\n<!-- todo: fix this -->\n\nSecond *one* here.");
    expect(plain).toBe("First paragraph here.\nSecond one here.");
  });
});

describe("findQuote", () => {
  it("matches straight quotes/dashes against curly ones and returns the doc's own characters", () => {
    expect(findQuote('"the lantern was still burning"', SCENE)).toBe("the lantern was still burning");
    expect(findQuote('still burning" - and then nothing more', SCENE)).toBe("still burning” — and then nothing more");
  });

  it("takes the longest piece of an ellipsised quote", () => {
    expect(findQuote("the lantern… was still burning and then nothing more", SCENE)).toBeNull();
    expect(findQuote("She said ... the lantern was still burning", SCENE)).toBe("the lantern was still burning");
  });

  it("rejects fewer than 3 words or fewer than 12 characters", () => {
    expect(findQuote("the lantern", SCENE)).toBeNull();
    expect(findQuote("rain on slate", "rain on slate")).toBe("rain on slate");
    expect(findQuote("a b c d e", "a b c d e")).toBeNull();
    expect(findQuote("lantern", SCENE)).toBeNull();
    expect(findQuote("lantern burning", "the lantern burning low")).toBeNull(); // 15 chars, 2 words
  });

  it("returns null when absent or when the quote spans blocks", () => {
    expect(findQuote("the lantern was out", SCENE)).toBeNull();
    expect(findQuote("nothing more. A second block", SCENE)).toBeNull();
    expect(findQuote("nothing more.\nA second block", SCENE)).toBeNull();
  });
});

describe("linkQuotes", () => {
  const plain = SCENE;
  const q = (html: string) => {
    const d = document.createElement("div");
    d.innerHTML = linkQuotes(html, plain);
    return d;
  };

  it("links an <em> quote with the doc's text", () => {
    const d = q("<p>Look at <em>the lantern was still burning</em> there.</p>");
    const el = d.querySelector("em.chat-quote-link") as HTMLElement;
    expect(el.dataset.quote).toBe("the lantern was still burning");
    expect(el.getAttribute("role")).toBe("link");
    expect(el.getAttribute("tabindex")).toBe("0");
  });

  it("links a blockquote paragraph", () => {
    const d = q("<blockquote><p>rain on slate</p></blockquote>");
    expect(d.querySelector("blockquote > p.chat-quote-link")).not.toBeNull();
  });

  it("links “…” and \"…\" runs in text, wrapping the quote marks", () => {
    const d = q('<p>He wrote “the lantern was still burning” and "rain on slate" ok.</p>');
    const spans = [...d.querySelectorAll("span.chat-quote-link")] as HTMLElement[];
    expect(spans.map((s) => s.textContent)).toEqual(["“the lantern was still burning”", '"rain on slate"']);
    expect(d.textContent).toBe('He wrote “the lantern was still burning” and "rain on slate" ok.');
  });

  it("never pairs a short quote's closing mark with the next quote's opening mark", () => {
    // Between the two quotes sits text that DOES occur in the scene.
    const d = q('<p>The "turn" the lantern was still burning "late".</p>');
    expect(d.querySelector("[data-quote]")).toBeNull();
  });

  it("does not link a paraphrase", () => {
    expect(q("<p>The lamp kept <em>on glowing all night</em>.</p>").querySelector("[data-quote]")).toBeNull();
  });

  it("leaves code and pre untouched", () => {
    const html = '<p><code>"the lantern was still burning"</code></p><pre>“rain on slate”</pre>';
    expect(q(html).querySelector("[data-quote]")).toBeNull();
  });

  it("never nests links", () => {
    const d = q("<blockquote><p><em>the lantern was still burning</em></p></blockquote>");
    expect(d.querySelectorAll("[data-quote]").length).toBe(1);
    expect(d.querySelector("blockquote > p")?.classList.contains("chat-quote-link")).toBe(true);
    expect(d.querySelector("[data-quote] [data-quote]")).toBeNull();
  });

  it("returns the html unchanged for an empty scene text", () => {
    const html = "<p><em>the lantern was still burning</em></p>";
    expect(linkQuotes(html, "")).toBe(html);
  });
});
