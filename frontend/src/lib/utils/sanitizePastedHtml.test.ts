// @vitest-environment happy-dom
import { describe, it, expect } from "vitest";
import { Schema } from "@tiptap/pm/model";
import { sanitizePastedHtml } from "./sanitizePastedHtml";
import { appClipboardSerializer } from "@/lib/editor-core/appClipboard";

describe("sanitizePastedHtml — the app's own clipboard (#2235)", () => {
  const pill = '<span data-mutation-set="mutation_set_1" data-mutation-id="mut_a" class="mutation-pill">⤳ Jar turn</span>';

  it("keeps the app's own inline nodes when the HTML was copied by the app's editor", () => {
    const schema = new Schema({
      nodes: {
        doc: { content: "block+" },
        paragraph: { content: "inline*", group: "block", toDOM: () => ["p", 0] },
        text: { group: "inline" },
        pill: {
          group: "inline",
          inline: true,
          atom: true,
          toDOM: () => ["span", { "data-mutation-set": "mutation_set_1", "data-mutation-id": "mut_a", class: "mutation-pill" }, "⤳ Jar turn"],
        },
      },
    });
    const content = schema.node("paragraph", null, [schema.text("Before "), schema.node("pill"), schema.text(" after")]);
    const wrap = document.createElement("div");
    wrap.appendChild(appClipboardSerializer(schema).serializeFragment(schema.node("doc", null, [content]).content, { document }));
    const out = sanitizePastedHtml(wrap.innerHTML);
    expect(out).toContain('data-mutation-id="mut_a"');
    expect(out).toContain('data-mutation-set="mutation_set_1"');
    expect(out).not.toContain("data-lwa-clipboard");
  });

  it("still flattens the same HTML when it comes from outside the app", () => {
    const out = sanitizePastedHtml(`<p>Before ${pill} after</p>`);
    expect(out).not.toContain("data-mutation-id");
    expect(out).toContain("⤳ Jar turn");
  });
});

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
