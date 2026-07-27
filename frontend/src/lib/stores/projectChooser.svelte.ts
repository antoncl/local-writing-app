// Project chooser — owns the "open a folder as a project" directory picker and
// the "new project" modal: their UI state, the folder-listing fetch, and the
// path-derivation logic. Extracted from App.svelte (#14 P0).
//
// Singleton rune controller (mirrors confirmService): one app shell
// mounts one of each modal, so a module-level instance with rune fields is
// correct and idiomatic. Not a writable store — traceable methods.
//
// The project LIFECYCLE (actually opening/creating a project) stays in App and
// is injected as callbacks (onOpenProject / onCreateProject), so this controller
// only drives the chooser UI and hands App a chosen path. App also pushes its
// machine-settings `defaultProjectsFolder` in (reactive) and supplies the
// picker's start directory + an error sink.

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
  // The picker component (DirectoryPickerModal) now owns its own browse state
  // (listing, roots, typed path) and fetches itself; this controller only says
  // WHEN it is open, WHERE it starts, and what to do with the chosen path.
  pickerOpen = $state(false);
  // Why the picker was opened, so a selection does the right thing on confirm.
  // Null = picker not open. "openProject" → open the picked folder immediately;
  // "newProjectOverride" → stash it as the new-project base folder.
  #mode = $state<"openProject" | "newProjectOverride" | null>(null);

  // ---- New Project modal ----
  newProjectOpen = $state(false);
  newProjectName = $state("");
  overrideFolder = $state(false);
  overridePath = $state("");

  // Default base folder, pushed in from App's machine settings (reactive).
  defaultProjectsFolder = $state("");

  // ---- Injected host hooks (set in App.onMount) ----
  // Report a validation error to the host (App's `error`).
  onError: (message: string) => void = () => {};
  // Open an existing project at the chosen path (App lifecycle).
  onOpenProject: (path: string) => void = () => {};
  // Create a project at path/title (App lifecycle).
  onCreateProject: (path: string, title: string) => Promise<void> = async () => {};
  // The directory the picker should start in (App's current project path).
  getStartPath: () => string = () => "";

  // Resolved destination for a new project, shown live in the modal.
  resolvedNewProjectPath = $derived(
    this.overrideFolder && this.overridePath
      ? joinPath(this.overridePath, slugifyProjectName(this.newProjectName))
      : joinPath(this.defaultProjectsFolder, slugifyProjectName(this.newProjectName)),
  );

  // Where the picker should start browsing, and its labels, per mode. Read by
  // App when it mounts the shared picker.
  get pickerInitialPath(): string {
    if (this.#mode === "newProjectOverride") {
      return (this.overridePath || this.defaultProjectsFolder || "").trim();
    }
    return this.getStartPath().trim();
  }

  get pickerTitle(): string {
    return this.#mode === "newProjectOverride" ? "Choose Parent Folder" : "Open Project Folder";
  }

  get pickerSelectLabel(): string {
    return this.#mode === "newProjectOverride" ? "Use This Folder" : "Open This Folder";
  }

  closePicker() {
    this.pickerOpen = false;
    this.#mode = null;
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
    this.pickerOpen = true;
  }

  openForNewProjectOverride() {
    this.#mode = "newProjectOverride";
    this.pickerOpen = true;
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
    // Where to *put* the new project, not what its layer chain is bounded by
    // (#429) — the bound is the machine root and is not sent per create.
    const parentFolder = this.overrideFolder && this.overridePath ? this.overridePath : this.defaultProjectsFolder;
    if (!parentFolder) {
      this.onError("No projects folder set. Open Settings to set a default.");
      return;
    }
    const path = joinPath(parentFolder, slugifyProjectName(this.newProjectName));
    this.closeNewProject();
    await this.onCreateProject(path, this.newProjectName.trim());
  }
}

export const projectChooser = new ProjectChooser();
