// Drift guard for the bundled Tabler subset (#315).
//
// The app ships only a curated slice of Tabler, not the full webfont, so a
// glyph the app uses but the subset omits renders as a blank box. These tests
// chain markup -> lists -> generated font:
//
//   1. every glyph the two source lists name exists as a rule in the generated
//      stylesheet (catches "added to a list but forgot `npm run icons:build`");
//   2. every static `ti ti-<name>` class written in src is covered by those
//      lists (catches "used a new glyph in markup but never curated it").
//
// When this fails: add the glyph to `CURATED_ICONS` (picker) or `UI_GLYPHS`
// (chrome), then run `npm run icons:build` and commit the regenerated files.

import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { CURATED_ICONS } from "@/lib/utils/fieldIcons";
import { UI_GLYPHS } from "@/lib/icons/uiGlyphs";

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(here, "..", "..");

// Glyph names the generated stylesheet defines a `.ti-<name>:before` rule for.
function bundledGlyphs(): Set<string> {
  const css = readFileSync(join(here, "generated", "tabler-subset.css"), "utf8");
  const names = new Set<string>();
  for (const m of css.matchAll(/\.ti-([a-z0-9-]+):before\{/g)) names.add(m[1]);
  return names;
}

// Every static `ti ti-<name>` class literal in a source file. Dynamic classes
// (`ti ti-${expr}`) yield no match — the `$` ends the name char class — so the
// scan sees only fully-written names; template fragments that end in a dash
// (e.g. `ti-layout-sidebar-${side}`) are dropped defensively.
function staticGlyphUsages(): Map<string, string> {
  const found = new Map<string, string>();
  const walk = (dir: string) => {
    for (const ent of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, ent.name);
      if (ent.isDirectory()) {
        if (ent.name === "generated" || ent.name === "node_modules") continue;
        walk(full);
      } else if (ent.name.endsWith(".svelte") || ent.name.endsWith(".ts")) {
        const text = readFileSync(full, "utf8");
        for (const m of text.matchAll(/\bti ti-([a-z0-9-]+)/g)) {
          const name = m[1];
          if (name.endsWith("-")) continue;
          if (!found.has(name)) found.set(name, full);
        }
      }
    }
  };
  walk(srcRoot);
  return found;
}

describe("bundled Tabler subset", () => {
  const bundled = bundledGlyphs();
  const listed = new Set([...CURATED_ICONS, ...UI_GLYPHS]);

  it("bundles every glyph the curated palette and chrome lists name", () => {
    const missing = [...listed].filter((name) => !bundled.has(name)).sort();
    expect(
      missing,
      `Listed but not in the generated font — run \`npm run icons:build\`: ${missing.join(", ")}`,
    ).toEqual([]);
  });

  it("has every statically-used ti-* class covered by the curated/chrome lists", () => {
    const usages = staticGlyphUsages();
    // Sanity: the scanner must actually find the many static usages in src.
    expect(usages.size).toBeGreaterThan(10);
    const uncovered = [...usages.entries()]
      .filter(([name]) => !listed.has(name))
      .map(([name, file]) => `${name} (${file})`)
      .sort();
    expect(
      uncovered,
      `Used in markup but not curated — add to CURATED_ICONS or UI_GLYPHS:\n${uncovered.join("\n")}`,
    ).toEqual([]);
  });
});
