// The curated Tabler icon palette — the writer-facing per-field icon picker set.
//
// This is PURE DATA with no imports, deliberately split out of `fieldIcons.ts`
// (which imports `@/lib/utils/colors`). The subset-font build script
// (`scripts/build-tabler-subset.mjs`) loads this list directly to know which
// glyphs to bundle; it transpiles the module and imports it from a `data:` URL,
// which cannot resolve `@/…` aliases — so the list it reads must not pull one in
// transitively. `fieldIcons.ts` re-exports everything here, so app consumers
// keep importing from `@/lib/utils/fieldIcons` unchanged.
//
// NOT the full ~5,147 Tabler glyphs — a writer-relevant set grouped by theme.
// Names are the bare Tabler glyph (no `ti-` prefix); all are real v3 icons.
export type IconCategory = { label: string; icons: string[] };

export const CURATED_ICON_CATEGORIES: IconCategory[] = [
  {
    label: "People",
    icons: [
      "user", "users", "user-circle", "mood-smile", "friends", "crown",
      "shield", "shield-half", "skull", "ghost", "heart", "heart-broken",
    ],
  },
  {
    label: "Places",
    icons: [
      "map-pin", "map", "map-2", "world", "building", "building-castle",
      "home", "tent", "mountain", "tree", "trees", "compass", "anchor",
      "sailboat", "route", "door",
    ],
  },
  {
    label: "Objects",
    icons: [
      "sword", "swords", "key", "lock", "lock-open", "book", "book-2", "books",
      "notebook", "writing-sign", "bookmark", "feather", "brush", "palette",
      "camera", "bell", "gift", "coin", "coins", "diamond", "tools",
      "hammer", "flask", "bottle", "cup", "briefcase", "folder", "cards", "bulb",
    ],
  },
  {
    label: "Nature & Time",
    icons: [
      "sun", "moon", "cloud", "cloud-rain", "snowflake", "leaf", "flower",
      "plant", "droplet", "flame", "bolt", "clock", "hourglass", "calendar",
      "calendar-event",
    ],
  },
  {
    label: "Story & Status",
    icons: [
      "target", "crosshair", "wall", "eye", "eye-off", "star", "sparkles",
      "flag", "alert-triangle", "check", "x", "circle-dot", "point",
      "wand", "mask",
    ],
  },
  {
    label: "Symbols",
    icons: [
      "tag", "tags", "link", "affiliate", "hash", "pin", "paperclip",
      "quote", "list-check", "list-numbers", "letter-case", "align-left",
      "toggle-right", "calculator", "stack-2", "layout-grid", "layout-board",
      "prompt", "arrows-shuffle", "message-circle",
    ],
  },
];

// Flat de-duplicated list, for search.
export const CURATED_ICONS: string[] = Array.from(
  new Set(CURATED_ICON_CATEGORIES.flatMap((category) => category.icons)),
);
