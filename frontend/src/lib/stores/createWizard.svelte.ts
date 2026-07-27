// Create-project wizard controller (#318 slice 2 — design-doc §4/§5 steps 1–2).
//
// Singleton rune controller, mirroring projectChooser: one app shell mounts one
// CreateProjectWizard, so a module-level instance with rune fields is idiomatic.
// The project LIFECYCLE (writing machine settings, scaffolding the project) stays
// in App/projectSession and is injected as callbacks; this controller only drives
// the multi-step UI, owns its own directory-picker instance, and hands the host a
// resolved path + declaration.
//
// This slice ends at step 2 with a Create action. Later slices insert AI / review
// / describe steps between "location" and Create; the stepper is built to absorb
// them by extending wizardSteps.ts, not this controller's shape.

import { api } from "@/lib/api";
import type { AncestorCandidate } from "@/lib/types";
import { joinPath, slugifyProjectName } from "@/lib/utils/projectPath";
import { declarationRows, toggledDeclaration } from "@/lib/utils/projectChain";
import { activeSteps, indexOfStep, stepComplete, type WizardStepId } from "@/lib/utils/wizardSteps";

class CreateWizard {
  open = $state(false);

  // Machine substrate, pushed from projectSession (mirrors how projectChooser
  // received defaultProjectsFolder). Empty ⇒ first run ⇒ the root-folder step.
  defaultProjectsFolder = $state("");

  // ---- Step 1: root folder ----
  rootFolderDraft = $state("");
  // Shown in the step body when saving the machine root fails. App's error toast
  // sits behind the modal (lower z-index), so the wizard must surface it itself.
  rootError = $state("");

  // ---- Step 2: location + inheritance ----
  title = $state("");
  pickedFolder = $state(""); // the parent folder chosen in the picker
  candidates = $state<AncestorCandidate[]>([]);
  candidatesLoading = $state(false);
  // Local source of truth for the ticks. The wizard has no project yet, so —
  // unlike the post-hoc editor (Project.svelte), which round-trips a save to
  // flip each candidate's `inherited` — this array *is* the round trip.
  inherits = $state<string[]>([]);

  // ---- Wizard-owned directory picker (its own instance, layered over Modal) ----
  pickerOpen = $state(false);
  #pickerMode = $state<"root" | "location" | null>(null);

  // ---- Navigation ----
  #stepIndex = $state(0);

  // ---- Injected host hooks (set in App.onMount) ----
  onError: (message: string) => void = () => {};
  onSaveRootFolder: (folder: string) => Promise<void> = async () => {};
  onCreateProject: (root: string, title: string, inherits: string[]) => Promise<void> = async () => {};
  getStartPath: () => string = () => "";

  // ---- Derived ----
  needsRootFolder = $derived(!this.defaultProjectsFolder.trim());
  steps = $derived(activeSteps(this.needsRootFolder));
  currentStep = $derived(this.steps[this.#stepIndex] ?? this.steps[this.steps.length - 1]);
  currentIndex = $derived(this.steps.indexOf(this.currentStep));
  isFinalStep = $derived(this.currentIndex === this.steps.length - 1);

  resolvedRoot = $derived(joinPath(this.pickedFolder, slugifyProjectName(this.title)));

  // Overlay the local selection onto each candidate's `inherited` flag so the
  // existing declarationRows / toggledDeclaration helpers work EXACTLY as they
  // do in Project.svelte. Do NOT "simplify" this to the raw candidates:
  // toggledDeclaration reads "currently declared" off `inherited`, which never
  // changes here (no save round-trip), so raw candidates would never accumulate.
  #selectedCandidates = $derived(
    this.candidates.map((candidate) => ({
      ...candidate,
      inherited: this.inherits.includes(candidate.path),
    })),
  );
  inheritRows = $derived(declarationRows(this.#selectedCandidates));

  canAdvance = $derived(
    stepComplete(this.currentStep.id, {
      rootFolderDraft: this.rootFolderDraft,
      title: this.title,
      pickedFolder: this.pickedFolder,
    }),
  );

  // ---- Picker labels (per mode), read by the mounted DirectoryPickerModal ----
  get pickerInitialPath(): string {
    if (this.#pickerMode === "location") {
      return (this.pickedFolder || this.defaultProjectsFolder || "").trim();
    }
    return (this.rootFolderDraft || this.getStartPath() || "").trim();
  }

  get pickerTitle(): string {
    return this.#pickerMode === "root" ? "Choose Projects Folder" : "Choose Location";
  }

  get pickerSelectLabel(): string {
    return "Use This Folder";
  }

  // ---- Lifecycle ----
  start() {
    this.reset();
    this.open = true;
  }

  reset() {
    this.rootFolderDraft = "";
    this.rootError = "";
    this.title = "";
    this.pickedFolder = "";
    this.candidates = [];
    this.candidatesLoading = false;
    this.inherits = [];
    this.#stepIndex = 0;
    this.pickerOpen = false;
    this.#pickerMode = null;
  }

  close() {
    this.open = false;
  }

  // ---- Step navigation ----
  goToStep(id: WizardStepId) {
    const index = indexOfStep(this.steps, id);
    // Breadcrumb navigation is backward-only: a completed step navigates back,
    // but a future step is unreachable by click (the consistency gate owns
    // forward motion through Next).
    if (index >= 0 && index < this.currentIndex) this.#stepIndex = index;
  }

  back() {
    if (this.#stepIndex > 0) this.#stepIndex -= 1;
  }

  async next() {
    // The view gates Next on canAdvance; guard anyway so a stray call is inert.
    if (!this.canAdvance) return;
    if (this.currentStep.id === "root") {
      this.rootError = "";
      await this.onSaveRootFolder(this.rootFolderDraft.trim());
      // On success the save flips defaultProjectsFolder ⇒ needsRootFolder ⇒ steps
      // collapses to ["location"]; #stepIndex 0 then already points at it
      // (isFinalStep true), so no increment is needed and none happens below.
      //
      // On FAILURE (e.g. the folder does not exist) the host swallows the error
      // into App's toast — which sits behind this modal — and needsRootFolder
      // stays true. Advancing anyway would build a project with no machine root
      // (a chain-of-one). So stay on the step and surface the failure here.
      if (this.needsRootFolder) {
        this.rootError = "Couldn't use that folder — check that the path exists.";
        return;
      }
    }
    if (!this.isFinalStep) this.#stepIndex += 1;
  }

  // ---- Directory picker ----
  openPicker(mode: "root" | "location") {
    this.#pickerMode = mode;
    this.pickerOpen = true;
  }

  closePicker() {
    this.pickerOpen = false;
    this.#pickerMode = null;
  }

  onPickFolder(path: string) {
    const mode = this.#pickerMode;
    this.closePicker();
    if (mode === "root") {
      this.rootFolderDraft = path;
      this.rootError = "";
      return;
    }
    if (mode === "location") {
      this.pickedFolder = path;
      void this.#loadCandidates(path);
    }
  }

  // The location can also be typed directly into the field; re-enumerate when it
  // is committed (on change/blur) so the candidate list tracks the typed folder,
  // not only a Browse selection.
  reloadCandidates() {
    void this.#loadCandidates(this.pickedFolder);
  }

  async #loadCandidates(folder: string) {
    // A new location means a new ancestry; previously-ticked paths may not even
    // exist under it, so start the declaration clean.
    this.inherits = [];
    this.candidatesLoading = true;
    try {
      // The candidates depend only on the parent folder (the walk excludes the
      // project's own slug), so a placeholder segment is enough to enumerate.
      const prospectiveRoot = joinPath(folder, slugifyProjectName(this.title));
      this.candidates = await api.prospectiveAncestorCandidates(prospectiveRoot);
    } catch (error) {
      this.candidates = [];
      this.onError(error instanceof Error ? error.message : "Could not read ancestor folders.");
    } finally {
      this.candidatesLoading = false;
    }
  }

  toggleInherit(path: string) {
    this.inherits = toggledDeclaration(this.#selectedCandidates, path);
  }

  // ---- Final action ----
  async submit() {
    if (!this.isFinalStep || !this.canAdvance) return;
    await this.onCreateProject(this.resolvedRoot, this.title.trim(), this.inherits);
    this.close();
  }
}

export const createWizard = new CreateWizard();
