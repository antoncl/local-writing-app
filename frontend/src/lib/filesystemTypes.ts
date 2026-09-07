// Filesystem-picker wire types. Extracted from types.ts to keep that barrel
// under the file-size cap; re-exported from `@/lib/types` so it stays the
// single import surface.

export type DirectoryEntry = {
  name: string;
  path: string;
  // Picker hints (#530): a folder that already holds a project, or an empty
  // folder that is a safe create target.
  is_project: boolean;
  is_empty: boolean;
};

export type DirectoryListing = {
  path: string;
  parent_path?: string | null;
  directories: DirectoryEntry[];
  // Whether the shown folder already holds a project (its "Select this folder" row).
  is_project: boolean;
  // Whether the shown folder is inside the machine projects root (#441). The
  // open-project picker refuses a folder outside it; other pickers ignore it.
  within_root: boolean;
};

// A jump-off point for the picker: a drive letter, home, or Documents (#530).
export type DirectoryRoot = {
  label: string;
  path: string;
  kind: "drive" | "home" | "documents";
};

// Non-throwing validation of a typed path, for the picker's path field (#530).
// `input` echoes the query so a stale reply can be ignored.
export type PathProbe = {
  input: string;
  is_dir: boolean;
  is_project: boolean;
};
