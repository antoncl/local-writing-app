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
  root.style.setProperty("--prose-indent", display.paragraph_indent ? INDENT : "0");
  // The blank line between paragraphs is its own choice (#2526): on keeps each
  // prose surface's own block-spacing default, off runs paragraphs together.
  if (display.paragraph_spacing) root.style.removeProperty("--prose-para-gap");
  else root.style.setProperty("--prose-para-gap", "0");
}
