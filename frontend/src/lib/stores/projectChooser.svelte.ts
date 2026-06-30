// Project chooser — owns the "open a folder as a project" directory picker and
// the "new project" modal: their UI state, the folder-listing fetch, and the
// path-derivation logic. Extracted from App.svelte (#14 P0).
//
// Singleton rune controller (mirrors paneLayout / confirmService): one app shell
// mounts one of each modal, so a module-level instance with rune fields is
// correct and idiomatic. Not a writable store — traceable methods.
//
// The project LIFECYCLE (actually opening/creating a project) stays in App and
// is injected as callbacks (onOpenProject / onCreateProject), so this controller
// only drives the chooser UI and hands App a chosen path. App also pushes its
// machine-settings `defaultProjectsFolder` in (reactive) and supplies the
// picker's start directory + an error sink.

import { api } from "@/lib/api";
import type { DirectoryListing } from "@/lib/types";

// Slugify mirrors the Python slugifyFieldId convention used elsewhere —
// lowercase, [a-z0-9-]+, no consecutive separators, no leading/trailing dashes.
// Used to derive the project folder name from the title.
function slugifyProjectName(name: string): string {
  const lowered = name.toLowerCase();
  const cleaned = lowered.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return cleaned || "new-project";
}

function joinPath(base: string, child: string): string {
  if (!base) return child;
  const sep = base.includes("\\") ? "\\" : "/";
  const trimmed = base.replace(/[/\\]+$/, "");
  return `${trimmed}${sep}${child}`;
}

class ProjectChooser {
  // ---- Directory picker ----
  pickerOpen = $state(false);
  listing = $state<DirectoryListing | null>(null);
  pickerLoading = $state(false);
  // Why the picker was opened, so a selection does the right thing on confirm.
  // Null = picker not open. "openProject" → open the picked folder immediately;
  // "newProjectOverride" → stash it as the new-project base folder.
  #mode: "openProject" | "newProjectOverride" | null = null;

  // ---- New Project modal ----
  newProjectOpen = $state(false);
  newProjectName = $state("");
  overrideFolder = $state(false);
  overridePath = $state("");

  // Default base folder, pushed in from App's machine settings (reactive).
  defaultProjectsFolder = $state("");

  // ---- Injected host hooks (set in App.onMount) ----
  // Wraps an action in App's run() so errors surface in App's `error`.
  onRun: (action: () => Promise<void>) => Promise<boolean> = async (action) => {
    await action();
    return true;
  };
  // Report a validation error to the host (App's `error`).
  onError: (message: string) => void = () => {};
  // Open an existing project at the chosen path (App lifecycle).
  onOpenProject: (path: string) => void = () => {};
  // Create a project at path/title (App lifecycle).
  onCreateProject: (path: string, title: string, baseFolder?: string) => Promise<void> = async () => {};
  // The directory the picker should start in (App's current project path).
  getStartPath: () => string = () => "";

  // Resolved destination for a new project, shown live in the modal.
  resolvedNewProjectPath = $derived(
    this.overrideFolder && this.overridePath
      ? joinPath(this.overridePath, slugifyProjectName(this.newProjectName))
      : joinPath(this.defaultProjectsFolder, slugifyProjectName(this.newProjectName)),
  );

  async #openPicker() {
    this.pickerOpen = true;
    await this.loadDirectory(this.getStartPath().trim() || undefined);
  }

  async loadDirectory(path?: string | null) {
    await this.onRun(async () => {
      this.pickerLoading = true;
      try {
        this.listing = await api.listDirectories(path ?? undefined);
      } finally {
        this.pickerLoading = false;
      }
    });
  }

  closePicker() {
    this.pickerOpen = false;
  }

  useDirectory(path: string) {
    const mode = this.#mode;
    this.pickerOpen = false;
    this.#mode = null;
    if (mode === "openProject") {
      this.onOpenProject(path);
    } else if (mode === "newProjectOverride") {
      this.overridePath = path;
      this.overrideFolder = true;
    }
  }

  openForOpenProject() {
    this.#mode = "openProject";
    void this.#openPicker();
  }

  openForNewProjectOverride() {
    this.#mode = "newProjectOverride";
    void this.#openPicker();
  }

  openNewProject() {
    this.newProjectName = "";
    this.overrideFolder = false;
    this.overridePath = "";
    this.newProjectOpen = true;
  }

  closeNewProject() {
    this.newProjectOpen = false;
  }

  clearOverride() {
    this.overrideFolder = false;
    this.overridePath = "";
  }

  async confirmNewProject() {
    if (!this.newProjectName.trim()) {
      this.onError("Project name is required.");
      return;
    }
    const baseFolder = this.overrideFolder && this.overridePath ? this.overridePath : this.defaultProjectsFolder;
    if (!baseFolder) {
      this.onError("No projects folder set. Open Settings to set a default.");
      return;
    }
    const path = joinPath(baseFolder, slugifyProjectName(this.newProjectName));
    this.closeNewProject();
    await this.onCreateProject(path, this.newProjectName.trim(), baseFolder);
  }
}

export const projectChooser = new ProjectChooser();
