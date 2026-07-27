// Project chooser — owns the "open a folder as a project" directory picker:
// its UI state, and what to do with the chosen path. Extracted from App.svelte
// (#14 P0).
//
// New-project creation moved to the create wizard (#318, createWizard.svelte.ts),
// which owns its own picker instance; this controller is now the open-project
// half alone. The path-derivation helpers it used to hold live in
// lib/utils/projectPath.ts, shared with the wizard.
//
// Singleton rune controller (mirrors confirmService): one app shell mounts one
// picker, so a module-level instance with rune fields is correct and idiomatic.
// Not a writable store — traceable methods.
//
// The project LIFECYCLE (actually opening a project) stays in App and is
// injected as a callback (onOpenProject), so this controller only drives the
// picker UI and hands App a chosen path. App also supplies the picker's start
// directory + an error sink.

class ProjectChooser {
  // The picker component (DirectoryPickerModal) owns its own browse state
  // (listing, roots, typed path) and fetches itself; this controller only says
  // WHEN it is open, WHERE it starts, and what to do with the chosen path.
  pickerOpen = $state(false);

  // ---- Injected host hooks (set in App.onMount) ----
  // Report a validation error to the host (App's `error`).
  onError: (message: string) => void = () => {};
  // Open an existing project at the chosen path (App lifecycle).
  onOpenProject: (path: string) => void = () => {};
  // The directory the picker should start in (App's current project path).
  getStartPath: () => string = () => "";

  // Where the picker should start browsing, and its labels. Read by App when it
  // mounts the shared picker.
  get pickerInitialPath(): string {
    return this.getStartPath().trim();
  }

  get pickerTitle(): string {
    return "Open Project Folder";
  }

  get pickerSelectLabel(): string {
    return "Open This Folder";
  }

  closePicker() {
    this.pickerOpen = false;
  }

  useDirectory(path: string) {
    this.pickerOpen = false;
    this.onOpenProject(path);
  }

  openForOpenProject() {
    this.pickerOpen = true;
  }
}

export const projectChooser = new ProjectChooser();
