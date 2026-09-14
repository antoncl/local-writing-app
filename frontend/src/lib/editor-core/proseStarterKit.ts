// The StarterKit configuration every prose surface that serialises to scene
// Markdown shares — the body editor (ProseBodyView) and the long_text metadata
// editor (MetadataLongTextEditor) — plus the round-trip test that pins it.
//
// StarterKit v3 newly bundles Link, Underline and TrailingNode ON by default.
// The scene Markdown grammar has no representation for a link or an underline
// mark (turndown would leak them as raw HTML and break md↔html↔md idempotency),
// and a permanent trailing empty paragraph would drift the saved body — so all
// three stay off. undoRedo (the renamed History) stays on for Ctrl+Z.
//
// Spelled once so a future StarterKit default cannot regress a single prose
// surface, and returned as a FRESH instance per editor: a StarterKit instance
// carries per-extension storage (e.g. undoRedo history), and a body editor and
// a long_text field can be mounted at the same time, so they must not share one.
import StarterKit from "@tiptap/starter-kit";

export function proseStarterKit() {
  return StarterKit.configure({
    heading: { levels: [1, 2, 3] },
    link: false,
    underline: false,
    trailingNode: false,
  });
}
