// Render the in-app guides as static pages for the website (#2556).
//
// One source: this reads the same bundle the in-app viewer ships
// (`src/lib/generated/guides.ts`, made by `scripts/gen_guides.py` from docs/) and
// renders it with the same `marked` the viewer uses, so a guide reads the same on
// the website as in the app — diagrams included (they are already inlined in the
// bundle). Nothing here is a second copy of a guide.
//
// What the website needs that the viewer does with click handlers instead:
//   - `#guide:<id>` links become `<id>.html`;
//   - headings get the viewer's slug as their `id`, so `#anchor` links resolve;
//   - a relative `.md` link goes to that guide's page if it is one, else to the
//     file on GitHub at the version being described.
//
// The pages workflow swaps in the bundle from the latest release tag before
// running this, so the website describes what people can download, not master.
//
// Usage: node scripts/build-site-guides.mjs [--out ../site/guides] [--version v1.0.0]

import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { Marked, Parser } from "marked";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, ".."); // frontend/
const REPO_URL = "https://github.com/antoncl/local-writing-app";

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const outDir = resolve(arg("out", resolve(root, "..", "site", "guides")));
const version = arg("version", "");

// The bundle is a typed TS module; Node 24 strips its types on import.
const bundleUrl = pathToFileURL(resolve(root, "src", "lib", "generated", "guides.ts")).href;
const { guides } = await import(bundleUrl);

/** GuideView's slug rule, so an `#anchor` written for the app resolves here too. */
function slugify(text) {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^\w]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// Plain text always comes from marked's text renderer over the tokens, never by
// stripping tags out of rendered HTML — that is an incomplete sanitizer (CodeQL
// js/incomplete-multi-character-sanitization). Text reaching a page is escaped.
const plainParser = new Parser();
const plainText = (tokens) => plainParser.parseInline(tokens, plainParser.textRenderer);
const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

const ids = new Set(guides.map((g) => g.id));

/** Where a link in a guide should point on the website. */
function rewriteHref(href, knownIds, ref) {
  if (href.startsWith("#guide:")) return `${href.slice("#guide:".length)}.html`;
  const md = href.match(/^(?:\.\/)?([\w./-]+)\.md(#.*)?$/);
  if (md) {
    const base = md[1].split("/").pop();
    if (knownIds.has(base)) return `${base}.html${md[2] ?? ""}`;
    return `${REPO_URL}/blob/${ref}/docs/${md[1]}.md${md[2] ?? ""}`;
  }
  return href;
}

function render(markdown) {
  const seen = new Map();
  const md = new Marked();
  md.use({
    renderer: {
      heading({ tokens, depth }) {
        const inner = this.parser.parseInline(tokens);
        const base = slugify(plainText(tokens));
        const n = seen.get(base) ?? 0;
        seen.set(base, n + 1);
        const id = n === 0 ? base : `${base}-${n}`;
        return `<h${depth} id="${id}">${inner}</h${depth}>\n`;
      },
    },
  });
  const html = md.parse(markdown);
  return html.replace(/href="([^"]+)"/g, (_, href) => `href="${rewriteHref(href, ids, version || "master")}"`);
}

const narrative = guides.filter((g) => g.kind !== "reference");
const reference = guides.filter((g) => g.kind === "reference");

function sidebar(currentId) {
  const item = (g) =>
    `<li><a href="${g.id}.html"${g.id === currentId ? ' aria-current="page"' : ""}>${escapeHtml(g.title)}</a></li>`;
  return `<nav class="guide-nav" aria-label="Guides">
  <p class="guide-nav-head"><a href="index.html">Guides</a></p>
  <ul>${narrative.map(item).join("")}</ul>
  <p class="guide-nav-head">Reference</p>
  <ul>${reference.map(item).join("")}</ul>
</nav>`;
}

const versionNote = version
  ? `These guides describe <a href="${REPO_URL}/releases/tag/${version}">${escapeHtml(version)}</a>, the latest release. The same guides are in the app under Help → Guides.`
  : "These guides describe the development version. The same guides are in the app under Help → Guides.";

function page({ title, description, body, currentId }) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)} — Local Writing App guides</title>
<meta name="description" content="${escapeHtml(description)}">
<link rel="icon" href="../assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>

<div class="topbar">
  <div class="wrap">
    <a class="home" href="../index.html">Local Writing App</a>
    <nav>
      <a href="../index.html">Home</a>
      <a href="index.html">Guides</a>
      <a href="../download.html">Download</a>
      <a href="${REPO_URL}">GitHub</a>
    </nav>
  </div>
</div>

<div class="wrap guide-layout">
${sidebar(currentId)}
<main class="guide-main">
<p class="guide-version">${versionNote}</p>
<article class="guide-prose">
${body}
</article>
</main>
</div>

<footer>
  <div class="wrap">
    <p>MIT licensed · <a href="${REPO_URL}">Source on GitHub</a> · <a href="${REPO_URL}/issues">Issues</a></p>
  </div>
</footer>

</body>
</html>
`;
}

/** A guide's pitch for the index: its first prose paragraph (a boxed aside such
 *  as "> User guide." is nested in a blockquote token, so it is skipped), cut at
 *  a sentence end near 200 characters. */
function pitch(markdown) {
  const p = new Marked().lexer(markdown).find((token) => token.type === "paragraph");
  const text = p ? plainText(p.tokens).replace(/\s+/g, " ").trim() : "";
  if (text.length <= 220) return text;
  const cut = text.slice(0, 220).match(/^.*[.!?](?=\s)/);
  return cut ? cut[0] : `${text.slice(0, 200).trimEnd()}…`;
}

rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });

const cards = [];
for (const guide of guides) {
  const body = render(guide.markdown);
  const description = pitch(guide.markdown);
  writeFileSync(resolve(outDir, `${guide.id}.html`), page({ title: guide.title, description, body, currentId: guide.id }));
  cards.push({ guide, description });
}

const card = ({ guide, description }) =>
  `<li class="guide-card"><a href="${guide.id}.html">${escapeHtml(guide.title)}</a><p>${escapeHtml(description)}</p></li>`;
const indexBody = `<h1>Guides</h1>
<p>How to use Local Writing App, from an empty window to writing your own AI prompts. New here? Start with <a href="getting-started.html">Getting started</a>.</p>
<ul class="guide-cards">${cards.filter((c) => c.guide.kind !== "reference").map(card).join("")}</ul>
<h2 id="reference">Reference</h2>
<ul class="guide-cards">${cards.filter((c) => c.guide.kind === "reference").map(card).join("")}</ul>`;
writeFileSync(
  resolve(outDir, "index.html"),
  page({ title: "Guides", description: "How to use Local Writing App.", body: indexBody, currentId: "" }),
);

console.log(`wrote ${guides.length + 1} pages to ${outDir}${version ? ` (${version})` : ""}`);
