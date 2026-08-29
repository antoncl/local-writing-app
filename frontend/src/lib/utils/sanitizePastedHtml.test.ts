// @vitest-environment happy-dom
import { describe, it, expect } from "vitest";
import { sanitizePastedHtml } from "./sanitizePastedHtml";

describe("sanitizePastedHtml — whole-document markdown source (#1622)", () => {
  it("re-parses a whole-document markdown code block as prose", () => {
    const html = '<pre><code class="language-markdown"># Title\n\n- one\n- two</code></pre>';
    const out = sanitizePastedHtml(html);
    expect(out).toContain("<h1"); // heading rendered as prose…
    expect(out).toContain("<li>"); // …list too…
    expect(out).not.toContain("<pre>"); // …and it is no longer a code block
  });

  it("leaves a real code sample (a non-markdown language) as a code block", () => {
    const html = '<pre><code class="language-python">def f():\n    return 1</code></pre>';
    const out = sanitizePastedHtml(html);
    expect(out).toContain("<pre>"); // still code
    expect(out).toContain("def f()");
  });

  it("leaves a code block with no language untouched", () => {
    const out = sanitizePastedHtml("<pre><code>plain code\nline two</code></pre>");
    expect(out).toContain("<pre>");
  });

  it("does not unwrap a markdown block that sits among other prose", () => {
    const html = '<p>Intro.</p><pre><code class="language-markdown"># heading</code></pre>';
    const out = sanitizePastedHtml(html);
    expect(out).toContain("<pre>"); // not the whole document → left as code
    expect(out).toContain("Intro.");
  });

  it("still strips presentational cruft from ordinary pasted prose", () => {
    const out = sanitizePastedHtml('<p style="color:red">hello <span class="x">world</span></p>');
    expect(out).not.toContain("style");
    expect(out).not.toContain("<span");
    expect(out).toContain("hello");
  });
});
