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
import type {
  AICapabilityTier,
  AIPolicy,
  AncestorCandidate,
  MachineSettingsView,
  ProviderCredentialsView,
} from "@/lib/types";
import { joinPath, slugifyProjectName } from "@/lib/utils/projectPath";
import { declarationRows, toggledDeclaration } from "@/lib/utils/projectChain";
import {
  addableCloudProviders,
  cloudKeyField,
  configuredCloudProviders,
  type ProviderOption,
} from "@/lib/utils/aiProviders";
import { activeSteps, indexOfStep, stepComplete, type WizardStepId } from "@/lib/utils/wizardSteps";

// The AI-policy draft: the three concrete stops plus the wire-only "inherit"
// (state no policy of your own — the chain resolves it, #471). Mirrors the
// AIPolicyDraft used by the Project pane.
export type AiPolicyDraft = AIPolicy | "inherit";

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

  // ---- Step 3: AI (design-doc §5 step 3) ----
  // The policy slider leads the step and gates the reveal below it. Default
  // "inherit" = state no policy; with a declared chain that inherits from the
  // ancestors, with none it resolves to the backend default (off). Picking a
  // concrete stop overrides here and unfolds the provider + assistant surface.
  aiPolicy = $state<AiPolicyDraft>("inherit");
  // "+ Add provider" credential entry (cloud only; Ollama's host is edited
  // inline under Local policy).
  addingProvider = $state(false);
  providerDraftId = $state("");
  providerDraftSecret = $state("");
  // Inline "Hire an assistant" draft.
  hiring = $state(false);
  hireTitle = $state("");
  hireProvider = $state("");
  hireTier = $state<AICapabilityTier | "">("");
  hireModel = $state("");
  // Guards the async provider-save / hire / curation buttons.
  aiBusy = $state(false);

  // ---- Wizard-owned directory picker (its own instance, layered over Modal) ----
  pickerOpen = $state(false);
  #pickerMode = $state<"root" | "location" | null>(null);

  // ---- Navigation ----
  #stepIndex = $state(0);

  // ---- Injected host hooks (set in App.onMount) ----
  onError: (message: string) => void = () => {};
  onSaveRootFolder: (folder: string) => Promise<void> = async () => {};
  // aiPolicy is applied to the freshly-created (now open) project by the host,
  // right after create; undefined leaves no stated policy (inherit).
  onCreateProject: (
    root: string,
    title: string,
    inherits: string[],
    aiPolicy: AIPolicy | undefined,
  ) => Promise<void> = async () => {};
  getStartPath: () => string = () => "";
  // Reads the live machine settings (the provider chooser's source of truth).
  // Injected rather than imported to avoid a cycle with projectSession; a
  // $derived that calls it still tracks the rune read at runtime, so the
  // "configured" set stays reactive when a credential is added.
  getMachineSettings: () => MachineSettingsView | null = () => null;
  // Provider credentials + assistants are machine-global substrate, so the host
  // writes them straight to the machine layer (layer_id ""); the new book
  // inherits the result. See the create-timing note on #547.
  onSaveProviderCredential: (
    field: keyof ProviderCredentialsView,
    value: string,
  ) => Promise<void> = async () => {};
  onHireAssistant: (
    title: string,
    provider: string,
    tier: AICapabilityTier | "",
    model: string,
  ) => Promise<void> = async () => {};
  onReorderAssistants: (orderedIds: string[]) => Promise<void> = async () => {};
  onUnlistAssistant: (entryId: string) => Promise<void> = async () => {};

  // ---- Derived ----
  needsRootFolder = $derived(!this.defaultProjectsFolder.trim());
  steps = $derived(activeSteps(this.needsRootFolder));
  currentStep = $derived(this.steps[this.#stepIndex] ?? this.steps[this.steps.length - 1]);
  currentIndex = $derived(this.steps.indexOf(this.currentStep));
  isFinalStep = $derived(this.currentIndex === this.steps.length - 1);

  resolvedRoot = $derived(joinPath(this.pickedFolder, slugifyProjectName(this.title)));

  // ---- AI-step derived ----
  // Inheriting is only meaningful when the author ticked an ancestor to inherit
  // from; a standalone / first-run project has nothing above it.
  canInheritPolicy = $derived(this.inherits.length > 0);
  // What the slider renders: with nothing to inherit, a resting "inherit" has no
  // stop to sit on, so it reads as the concrete default (off).
  aiSliderValue = $derived<AiPolicyDraft>(
    this.canInheritPolicy ? this.aiPolicy : this.aiPolicy === "inherit" ? "off" : this.aiPolicy,
  );
  // The provider + assistant surface unfolds only for a concrete on-policy stated
  // here. Off hides it; inheriting hides it too (you are taking the ancestors'
  // whole AI setup, providers included — nothing to configure at this layer).
  showProviderSurface = $derived(
    this.aiPolicy === "local-only" || this.aiPolicy === "cloud-allowed",
  );
  providerModeCloud = $derived(this.aiPolicy === "cloud-allowed");
  // The provider chooser's data, derived from the live machine settings so it
  // updates the moment a credential is written.
  configuredProviders = $derived<ProviderOption[]>(
    configuredCloudProviders(this.getMachineSettings()?.providers),
  );
  addableProviders = $derived<ProviderOption[]>(
    addableCloudProviders(this.getMachineSettings()?.providers),
  );
  defaultProviderId = $derived(this.getMachineSettings()?.default_provider ?? "");
  ollamaHost = $derived(this.getMachineSettings()?.providers.ollama_host ?? "");
  // Persisted to the new project only when a concrete policy is stated here;
  // "inherit" writes nothing so the chain resolves it (§7's inheritance law).
  #aiPolicyToPersist = $derived<AIPolicy | undefined>(
    this.aiPolicy === "inherit" ? undefined : this.aiPolicy,
  );

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
    this.aiPolicy = "inherit";
    this.cancelAddProvider();
    this.cancelHire();
    this.aiBusy = false;
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

  // ---- AI step ----
  // Runs an async curation gesture under the shared busy guard: re-entrant calls
  // are dropped, and aiBusy is always cleared. Every provider/assistant write
  // goes through here so the guarding rule lives in one place.
  async #withBusy(fn: () => Promise<void>) {
    if (this.aiBusy) return;
    this.aiBusy = true;
    try {
      await fn();
    } finally {
      this.aiBusy = false;
    }
  }

  #resetHireDraft() {
    this.hireTitle = "";
    this.hireProvider = "";
    this.hireTier = "";
    this.hireModel = "";
  }

  setAiPolicy(next: AiPolicyDraft) {
    this.aiPolicy = next;
    // Leaving an on-policy collapses the provider surface, so drop any half-typed
    // add-provider / hire drafts rather than carry them into a hidden section.
    if (next === "off" || next === "inherit") {
      this.cancelAddProvider();
      this.cancelHire();
    }
  }

  beginAddProvider(providerId: string) {
    this.addingProvider = true;
    this.providerDraftId = providerId;
    this.providerDraftSecret = "";
  }

  cancelAddProvider() {
    this.addingProvider = false;
    this.providerDraftId = "";
    this.providerDraftSecret = "";
  }

  async saveProvider() {
    const field = cloudKeyField(this.providerDraftId);
    const value = this.providerDraftSecret.trim();
    if (!field || !value) return;
    await this.#withBusy(async () => {
      await this.onSaveProviderCredential(field, value);
      this.cancelAddProvider();
    });
  }

  beginHire() {
    this.hiring = true;
    this.#resetHireDraft();
  }

  cancelHire() {
    this.hiring = false;
    this.#resetHireDraft();
  }

  setHireProvider(provider: string, tier: AICapabilityTier | "", model: string) {
    this.hireProvider = provider;
    this.hireTier = tier;
    this.hireModel = model;
  }

  async submitHire() {
    await this.#withBusy(async () => {
      await this.onHireAssistant(
        this.hireTitle.trim() || "New assistant",
        this.hireProvider,
        this.hireTier,
        this.hireModel,
      );
      this.cancelHire();
    });
  }

  async reorderAssistants(orderedIds: string[]) {
    await this.#withBusy(() => this.onReorderAssistants(orderedIds));
  }

  async unlistAssistant(entryId: string) {
    await this.#withBusy(() => this.onUnlistAssistant(entryId));
  }

  // ---- Final action ----
  async submit() {
    if (!this.isFinalStep || !this.canAdvance) return;
    await this.onCreateProject(
      this.resolvedRoot,
      this.title.trim(),
      this.inherits,
      this.#aiPolicyToPersist,
    );
    this.close();
  }
}

export const createWizard = new CreateWizard();
