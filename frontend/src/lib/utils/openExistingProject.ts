// First-run "open an existing project" helpers (#2467). Pure / injected so the
// create wizard's store stays small and these rules are unit-testable.
//
// Opening a project requires it to sit under the machine projects folder (#441:
// inheritance needs a bound), so a first-run opener must also pick that folder.
// We suggest the parent of the TOPMOST ancestor project, which keeps a book's
// whole series / world chain under the root.

import type { DirectoryListing } from "@/lib/filesystemTypes";

type ListDirectories = (path?: string) => Promise<DirectoryListing>;

// Walk up from a project folder through `parent_path` while the parent is itself
// a project; the suggestion is the parent of the last project found. A folder
// with no parent (a filesystem root) suggests itself.
export async function suggestProjectsFolder(
  listing: DirectoryListing,
  list: ListDirectories,
): Promise<string> {
  let top = listing;
  while (top.parent_path) {
    const parent = await list(top.parent_path);
    if (!parent.is_project) break;
    top = parent;
  }
  return top.parent_path ?? top.path;
}

// Windows-style paths (drive letter, UNC, or backslashes) compare
// case-insensitively; POSIX paths do not.
function normalized(path: string): { text: string; windows: boolean } {
  const trimmed = path.trim();
  const windows = /^[a-z]:/i.test(trimmed) || trimmed.includes("\\");
  const text = trimmed.replace(/[\\/]+/g, "/").replace(/\/+$/, "");
  return { text: windows ? text.toLowerCase() : text, windows };
}

// Whether `project` lies strictly inside `root` — separator-aware, so
// `D:\Books2\x` is not inside `D:\Books`.
export function rootContainsProject(root: string, project: string): boolean {
  const base = normalized(root);
  const child = normalized(project);
  if (!root.trim() || !project.trim()) return false;
  if (base.windows !== child.windows) return false;
  return child.text.startsWith(`${base.text}/`);
}
