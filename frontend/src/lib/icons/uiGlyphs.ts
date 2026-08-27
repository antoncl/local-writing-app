// App-chrome Tabler glyphs — the icons the app's OWN UI renders directly in
// markup (buttons, toggles, rail affordances, dialog controls), as opposed to
// the writer-facing picker palette in `CURATED_ICON_CATEGORIES`
// (`@/lib/utils/fieldIcons`).
//
// This list, unioned with `CURATED_ICONS`, is the exact set of glyphs baked
// into the shipped subset font (see `frontend/scripts/build-tabler-subset.mjs`
// and `src/lib/icons/generated/`). The full 5,147-glyph webfont is NOT
// bundled — a name absent from both lists renders as a blank box.
//
// Keep it complete: `src/lib/icons/tablerSubset.test.ts` scans the source for
// literal `ti ti-*` classes and fails if any used glyph is missing here (or in
// the curated palette) or absent from the generated subset. When that test
// flags a new glyph, add it here and re-run `npm run icons:build`.
//
// Provenance for the current entries: the icon-usage sweep for #315 (static
// markup, the `AiPolicySlider` STOPS trio, and the `stack-2` group fallback).
// Some entries (e.g. `check`, `tag`, `cloud`, `eye`) also appear in the curated
// palette; they are listed here too so this stays a self-contained record of
// what the chrome depends on regardless of picker curation.
export const UI_GLYPHS: string[] = [
  "alert-circle",
  "alert-triangle",
  "arrow-back-up",
  "arrow-bar-to-left",
  "arrow-bar-to-right",
  "arrow-forward-up",
  "arrow-merge",
  "arrow-up",
  "check",
  "chevron-down",
  "chevron-left",
  "chevron-right",
  "chevron-up",
  "cloud",
  "device-desktop",
  "dots-vertical",
  "eye",
  "eye-off",
  "grip-vertical",
  "home",
  "info-circle",
  "layout-sidebar-left-collapse",
  "layout-sidebar-left-expand",
  "layout-sidebar-right-collapse",
  "layout-sidebar-right-expand",
  "lock",
  "pencil",
  "player-play",
  "plus",
  "power",
  "seedling",
  "settings",
  "stack-2",
  "tag",
  "trash",
  "unlink",
  "versions",
  "x",
];
