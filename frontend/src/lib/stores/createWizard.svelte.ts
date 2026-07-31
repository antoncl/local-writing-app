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
  MetadataSchema,
  MetadataValue,
  ProviderCredentialsView,
} from "@/lib/types";
import { joinPath, slugifyProjectName } from "@/lib/utils/projectPath";
import { declarationRows, toggledDeclaration } from "@/lib/utils/projectChain";
import { projectReviewRows } from "@/lib/utils/projectReview";
import { activeSteps, indexOfStep, stepComplete, type WizardStepId } from "@/lib/utils/wizardSteps";

// Zero-value credentials so `machineProviders` is always a concrete
// ProviderCredentialsView (getMachineSettings() is null before settings load);
// ProviderSubscriptions derives "configured"/"addable" from it either way.
const EMPTY_PROVIDER_CREDENTIALS: ProviderCredentialsView = {
  anthropic_api_key: "",
  openai_api_key: "",
  openrouter_api_key: "",
  ollama_host: "",
};

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
  // Inline "Hire an assistant" draft.
  hiring = $state(false);
  hireTitle = $state("");
  hireProvider = $state("");
  hireTier = $state<AICapabilityTier | "">("");
  hireModel = $state("");
  // Guards the async provider-save / hire / curation buttons.
  aiBusy = $state(false);

  // ---- Step 4: review — book settings / overrides (design-doc §5 step 4) ----
  // The project node's authored fields, resolved over the ticked chain *before*
  // the project exists (`prospective_project_node`). The pane shows the full
  // filled-in picture; `nodeOverrides` holds only the fields the author sets
  // here, which is exactly what gets written to the new book's `project.md` —
  // everything else stays absent and inherits (§7's pop-key model).
  reviewLoading = $state(false);
  reviewSchema = $state<MetadataSchema | null>(null);
  reviewInherited = $state<Record<string, MetadataValue>>({});
  reviewSources = $state<Record<string, string>>({});
  nodeOverrides = $state<Record<string, MetadataValue>>({});

  // ---- Step 5: describe (design-doc §5 step 5) ----
  // A short blurb into the project node body. Skippable.
  description = $state("");

  // ---- Wizard-owned directory picker for the Location step (its own instance,
  // layered over Modal). The root step has its own picker (ProjectsFolderPicker,
  // ADR-0047 slice 4), so this one only ever targets the project location. ----
  pickerOpen = $state(false);

  // ---- Navigation ----
  #stepIndex = $state(0);
  // Whether this run began with no machine root configured — i.e. first run
  // (#746). Snapshotted at `start()`, because the root step flips
  // `needsRootFolder` false mid-flow, and submit needs to know where the AI
  // policy belongs: the app-wide default (first run) or the new project
  // (subsequent). See `submit()`.
  #firstRun = $state(false);

  // ---- Injected host hooks (set in App.onMount) ----
  onError: (message: string) => void = () => {};
  onSaveRootFolder: (folder: string) => Promise<void> = async () => {};
  // aiPolicy is applied to the freshly-created (now open) project by the host,
  // right after create; undefined leaves no stated policy (inherit).
  // `nodeMetadata` is the review pane's overrides (only the fields the author
  // set here) and `description` the blurb — both written into the new book's
  // `project.md` post-create, mirroring the aiPolicy timing (§7's pop-key model:
  // an unset field is simply absent and inherits).
  onCreateProject: (
    root: string,
    title: string,
    inherits: string[],
    aiPolicy: AIPolicy | undefined,
    nodeMetadata: Record<string, MetadataValue>,
    description: string,
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
  // Write the application-global default AI policy (#746), from the first-run AI
  // step. Machine-global substrate, like the provider credentials and assistants
  // beside it — the new book inherits it. Awaited before create so the freshly
  // created project resolves against it. Unused on subsequent runs (the policy
  // is per-project then).
  onSaveAppPolicy: (policy: AIPolicy) => Promise<void> = async () => {};
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
  // The raw machine credentials, fed to ProviderSubscriptions (it derives the
  // configured/addable sets itself). Derived from the live machine settings so
  // the chip list updates the moment a credential is written.
  machineProviders = $derived<ProviderCredentialsView>(
    this.getMachineSettings()?.providers ?? EMPTY_PROVIDER_CREDENTIALS,
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

  // ---- Review-step derived ----
  // One row per authored project field, resolved over the ticked chain. Pure
  // and tested in projectReview.ts; empty until the prospective resolve lands.
  reviewRows = $derived(
    this.reviewSchema
      ? projectReviewRows(
          this.reviewSchema,
          this.reviewInherited,
          this.reviewSources,
          this.nodeOverrides,
        )
      : [],
  );

  // ---- Location-picker labels, read by the mounted DirectoryPickerModal ----
  get pickerInitialPath(): string {
    return (this.pickedFolder || this.defaultProjectsFolder || "").trim();
  }

  get pickerTitle(): string {
    return "Choose Location";
  }

  get pickerSelectLabel(): string {
    return "Use This Folder";
  }

  // ---- Lifecycle ----
  start() {
    this.reset();
    // Snapshot first-run before the root step can flip it (#746 — see submit()).
    this.#firstRun = this.needsRootFolder;
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
    this.cancelHire();
    this.aiBusy = false;
    this.reviewLoading = false;
    this.reviewSchema = null;
    this.reviewInherited = {};
    this.reviewSources = {};
    this.nodeOverrides = {};
    this.description = "";
    this.#stepIndex = 0;
    this.pickerOpen = false;
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
    if (!this.isFinalStep) {
      this.#stepIndex += 1;
      // The review step resolves the project node against the chain declared at
      // the location step; fetch it on entry (the AI step between them cannot
      // change the ancestry). Re-entering after a Back re-fetches — cheap, and
      // it keeps the inherited picture honest if the declaration changed.
      if (this.currentStep.id === "review") void this.#loadReview();
    }
  }

  async #loadReview() {
    this.reviewLoading = true;
    try {
      const node = await api.prospectiveProjectNode(this.resolvedRoot, this.inherits);
      this.reviewSchema = node.metadata_schema;
      this.reviewInherited = node.metadata;
      this.reviewSources = node.field_sources;
    } catch (error) {
      this.reviewSchema = null;
      this.onError(
        error instanceof Error ? error.message : "Could not resolve the project's settings.",
      );
    } finally {
      this.reviewLoading = false;
    }
  }

  // ---- Directory picker ----
  openPicker() {
    this.pickerOpen = true;
  }

  closePicker() {
    this.pickerOpen = false;
  }

  onPickFolder(path: string) {
    this.closePicker();
    this.pickedFolder = path;
    void this.#loadCandidates(path);
  }

  // The location can also be typed directly into the field; re-enumerate when it
  // is committed (on change/blur) so the candidate list tracks the typed folder,
  // not only a Browse selection.
  reloadCandidates() {
    void this.#loadCandidates(this.pickedFolder);
  }

  async #loadCandidates(folder: string) {
    // A new location means a new ancestry; previously-ticked paths may not even
    // exist under it, so start the declaration clean — and drop any field
    // overrides, whose inherited baseline is about to change.
    this.inherits = [];
    this.nodeOverrides = {};
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
    // hire draft rather than carry it into a hidden section. (The add-provider
    // form now lives in ProviderSubscriptions, which unmounts with the surface.)
    if (next === "off" || next === "inherit") {
      this.cancelHire();
    }
  }

  // ProviderSubscriptions owns the add-form state and resolves the target field;
  // it hands us a (field, value) to persist. The wizard writes each key
  // immediately (machine layer — the new book inherits it), so wrap the write in
  // the shared busy guard that disables the widget's Save while it's in flight.
  async saveProviderKey(field: keyof ProviderCredentialsView, value: string) {
    const trimmed = value.trim();
    if (!trimmed) return;
    await this.#withBusy(() => this.onSaveProviderCredential(field, trimmed));
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

  // ---- Review step (book settings / overrides) ----
  // Setting a field authors it here (a live override); resetting pops it back to
  // inherit/default. Presence — not equality with the inherited value — is the
  // signal, matching the pop-key model the backend write uses.
  setNodeField(fieldId: string, value: MetadataValue) {
    this.nodeOverrides = { ...this.nodeOverrides, [fieldId]: value };
  }

  resetNodeField(fieldId: string) {
    const next = { ...this.nodeOverrides };
    delete next[fieldId];
    this.nodeOverrides = next;
  }

  setDescription(value: string) {
    this.description = value;
  }

  // ---- Final action ----
  async submit() {
    if (!this.isFinalStep || !this.canAdvance) return;
    // §7 (#746): on first run the AI-step policy establishes the APP-WIDE
    // default (the machine layer — there is no root project to hold it), and the
    // first project states nothing, inheriting it. On subsequent creation the
    // policy is a per-project choice, applied to the new project. Either way
    // "inherit" (#aiPolicyToPersist === undefined) writes nothing and the chain
    // resolves it.
    if (this.#firstRun && this.#aiPolicyToPersist) {
      await this.onSaveAppPolicy(this.#aiPolicyToPersist);
    }
    await this.onCreateProject(
      this.resolvedRoot,
      this.title.trim(),
      this.inherits,
      this.#firstRun ? undefined : this.#aiPolicyToPersist,
      this.nodeOverrides,
      this.description.trim(),
    );
    this.close();
  }
}

export const createWizard = new CreateWizard();
