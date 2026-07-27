// Project-path derivation shared by the create wizard and the open-project
// chooser. Extracted from projectChooser (#318) so the wizard and the chooser
// build folder names one way, not two.

// Slugify mirrors the Python slugifyFieldId convention used elsewhere —
// lowercase, [a-z0-9-]+, no consecutive separators, no leading/trailing dashes.
// Used to derive the project folder name from the title.
export function slugifyProjectName(name: string): string {
  const lowered = name.toLowerCase();
  const cleaned = lowered.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return cleaned || "new-project";
}

// Join a child segment onto a base path, honouring the base's separator so a
// Windows path stays `\`-joined and a POSIX path stays `/`-joined.
export function joinPath(base: string, child: string): string {
  if (!base) return child;
  const sep = base.includes("\\") ? "\\" : "/";
  const trimmed = base.replace(/[/\\]+$/, "");
  return `${trimmed}${sep}${child}`;
}
