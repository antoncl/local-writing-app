// Prose-presentation prefs (#127 / #575) applied as CSS custom properties on the
// document root — the same mechanism as theme.ts. Display-only: the master type
// scaler (`--ui-scale`, which every `--fs-*` token multiplies through) and
// paragraph formatting (`--prose-align`, `--prose-indent`, and a coupled
// `--prose-para-gap`). Never touches stored prose.

import type { DisplaySettings } from "@/lib/types";

// First-line indent when enabled — one "tab" worth, in em so it tracks font size.
const INDENT = "1.5em";

export function applyProsePresentation(display: DisplaySettings): void {
  const root = document.documentElement;
  root.style.setProperty("--ui-scale", String(display.ui_scale));
  root.style.setProperty("--prose-align", display.paragraph_align);
  if (display.paragraph_indent) {
    root.style.setProperty("--prose-indent", INDENT);
    // Indented paragraphs run continuous — no blank line between them.
    root.style.setProperty("--prose-para-gap", "0");
  } else {
    root.style.setProperty("--prose-indent", "0");
    // Flush paragraphs keep each prose surface's own block-spacing default.
    root.style.removeProperty("--prose-para-gap");
  }
}
