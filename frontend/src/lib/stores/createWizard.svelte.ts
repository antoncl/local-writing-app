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
  ProspectiveAiPolicy,
  ProviderCredentialsView,
} from "@/lib/types";
import { joinPath, slugifyProjectName } from "@/lib/utils/projectPath";
import { declarationRows, toggledDeclaration } from "@/lib/utils/projectChain";
import { projectReviewRows } from "@/lib/utils/projectReview";
import { localeProjectDefaults } from "@/lib/utils/localeDefaults";
import { providersForPolicy } from "@/lib/utils/aiProviders";
import { suggestProjectsFolder } from "@/lib/utils/openExistingProject";
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
  // The chosen model's display name (#1412) — the default assistant name when the
  // author doesn't type one, so the roster reads e.g. "Claude Sonnet 4.6" instead
  // of a wall of identical "New assistant" rows.
  hireModelLabel = $state("");
  // Guards the async provider-save / hire / curation buttons.
  aiBusy = $state(false);
  // What the "inherit" state would actually resolve to, and from where (#1672) —
  // fetched on entering the AI step so the slider's inherit note names the value
  // and its provenance instead of a vague "from the projects above". Null when
  // there's nothing to inherit or the fetch failed (the note falls back to the
  // generic copy).
  inheritedPolicy = $state<ProspectiveAiPolicy | null>(null);

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
  // What the picker is choosing: the project location, or (first run, #2467) an
  // existing project to open.
  pickerMode = $state<"location" | "open">("location");

  // ---- First-run "open an existing project" (#2467) ----
  // The project picked on the Welcome step; "" outside the open flow.
  openProjectPath = $state("");
  // Inline feedback on the Welcome / open-root steps (the app's error toast sits
  // behind this modal).
  openError = $state("");
  openBusy = $state(false);
  // Choosing Open swaps the step list for start + open_root (wizardSteps.ts).
  #opening = $state(false);
  // Whether the Welcome step is still reachable: true for a first-run session
  // until the Create path moves past the root step (then Welcome drops out, as the
  // root step always did). Open keeps it true, so Back from open_root always lands
  // on a Welcome step offering both choices - even after the root was saved and
  // the open then failed (needsRootFolder is false by then).
  #welcome = $state(false);
  // Bumped whenever the Welcome step is left, the wizard closes or resets, or a
  // new pick starts - a slow #pickExisting that finds it changed bails silently.
  #pickToken = 0;

  // ---- Navigation ----
  #stepIndex = $state(0);
  // Whether this run began with no machine root configured — i.e. first run
  // (#746). Snapshotted at `start()`, because the root step flips
  // `needsRootFolder` false mid-flow, and submit needs to know where the AI
  // policy belongs: the app-wide default (first run) or the new project
  // (subsequent). See `submit()`.
  #firstRun = $state(false);
  // Locale defaults are seeded into the review overrides once per location
  // (#1415). Reset on `reset()` and whenever the ancestry changes
  // (`#loadCandidates`), so a new chain re-seeds; kept across Back/forward within
  // one location so an author's edits and resets are never re-clobbered.
  #localeSeeded = false;

  // ---- Injected host hooks (set in App.onMount) ----
  onError: (message: string) => void = () => {};
  onSaveRootFolder: (folder: string) => Promise<void> = async () => {};
  // First-run "open an existing project" (#2467): resolves false when the open
  // failed (the host has already surfaced the error).
  onOpenProject: (path: string) => Promise<boolean> = async () => true;
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
  // Resolves false when the write failed (the host has already surfaced it) - the
  // first-run Open path (#2467) keeps the wizard open on that.
  onSaveAppPolicy: (policy: AIPolicy) => Promise<boolean | void> = async () => {};
  onHireAssistant: (
    title: string,
    provider: string,
    tier: AICapabilityTier | "",
    model: string,
  ) => Promise<void> = async () => {};
  onReorderAssistants: (orderedIds: string[]) => Promise<void> = async () => {};
  onUnlistAssistant: (entryId: string) => Promise<void> = async () => {};
  // Load the machine roster the AI step shows (#2448). Fired on every start:
  // nothing else keeps it current while no machine write has happened.
  onStart: () => void = () => {};

  // ---- Derived ----
  needsRootFolder = $derived(!this.defaultProjectsFolder.trim());
  steps = $derived(activeSteps(this.needsRootFolder, this.#opening, this.#welcome));
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
  // ADR-0073 S2: the resolved policy fed to ProviderTierPicker — never the
  // wire-only "inherit". showProviderSurface only renders the picker for a
  // concrete stop, so this is really just a type-narrowing fallback; "off" is
  // the same resting value aiSliderValue reads for "nothing to inherit".
  pickerPolicy = $derived<AIPolicy>(this.aiPolicy === "inherit" ? "off" : this.aiPolicy);
  // The provider ids the chooser may show at this stop — the ONLY thing the
  // policy slider does to the provider surface: "local-only" → Ollama alone;
  // "cloud-allowed" → every provider (Ollama + cloud). Moving the slider up just
  // widens this set; nothing swaps out (#1417). Folds "inherit" via pickerPolicy.
  providerScope = $derived<string[]>(providersForPolicy(this.pickerPolicy));
  // The raw machine credentials, fed to ProviderSubscriptions (it derives the
  // configured/addable sets itself). Derived from the live machine settings so
  // the chip list updates the moment a credential is written.
  machineProviders = $derived<ProviderCredentialsView>(
    this.getMachineSettings()?.providers ?? EMPTY_PROVIDER_CREDENTIALS,
  );
  defaultProviderId = $derived(this.getMachineSettings()?.default_provider ?? "");
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
      openProjectPath: this.openProjectPath,
    }),
  );

  // Authoritative completion gate (#1404). `canAdvance` on the FINAL step
  // ("describe") is unconditionally true, so it cannot protect the title; Create
  // instead requires the actual submitted fields (a set root + a title + a
  // folder) regardless of which step is current. A skipped or invalid earlier
  // step then can never complete into a backend 422 — the guarantee the sole
  // location-step gate lost once "location" stopped being the last step.
  canComplete = $derived(
    !this.needsRootFolder &&
      stepComplete("location", {
        rootFolderDraft: this.rootFolderDraft,
        title: this.title,
        pickedFolder: this.pickedFolder,
        openProjectPath: this.openProjectPath,
      }),
  );

  // Inline "name required" feedback (#1404): shown only after the field is
  // touched (blurred) so a freshly-entered step does not nag. Mirrors the
  // `rootError` channel — the same `.wizard-error` markup renders it.
  titleTouched = $state(false);
  titleError = $derived(
    this.titleTouched && this.title.trim().length === 0 ? "Project name is required." : "",
  );

  markTitleTouched() {
    this.titleTouched = true;
  }

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
    if (this.pickerMode === "open") return (this.defaultProjectsFolder || this.getStartPath()).trim();
    return (this.pickedFolder || this.defaultProjectsFolder || "").trim();
  }

  get pickerTitle(): string {
    return this.pickerMode === "open" ? "Open Your Project" : "Choose Location";
  }

  get pickerSelectLabel(): string {
    return this.pickerMode === "open" ? "Open This Project" : "Use This Folder";
  }

  // ---- Lifecycle ----
  start() {
    this.reset();
    // Snapshot first-run before the root step can flip it (#746 — see submit()).
    this.#firstRun = this.needsRootFolder;
    this.#welcome = this.#firstRun;
    // Returning user (a machine root is already set): seed the Location field
    // with it so the shown default actually counts (#1410). First run seeds
    // after the root step instead (next()).
    this.#seedLocationFromDefault();
    this.onStart();
    this.open = true;
  }

  // Default the Location to the machine root so it is a real, usable value rather
  // than a placeholder the gate ignores (#1410). The Next gate, the "will be
  // created at" line, and the Inherit list all key off `pickedFolder`, so leaving
  // it empty kept Next disabled even though the default was displayed. The picker
  // stays for choosing a DIFFERENT parent (e.g. nesting under an existing
  // project), not for re-picking the obvious default. No-op once a folder is set.
  #seedLocationFromDefault() {
    const root = this.defaultProjectsFolder.trim();
    if (root && !this.pickedFolder) {
      this.pickedFolder = root;
      void this.#loadCandidates(root);
    }
  }

  reset() {
    this.rootFolderDraft = "";
    this.rootError = "";
    this.title = "";
    this.titleTouched = false;
    this.pickedFolder = "";
    this.candidates = [];
    this.candidatesLoading = false;
    this.inherits = [];
    this.aiPolicy = "inherit";
    this.inheritedPolicy = null;
    this.cancelHire();
    this.aiBusy = false;
    this.reviewLoading = false;
    this.reviewSchema = null;
    this.reviewInherited = {};
    this.reviewSources = {};
    this.nodeOverrides = {};
    this.#localeSeeded = false;
    this.description = "";
    this.#stepIndex = 0;
    this.pickerOpen = false;
    this.pickerMode = "location";
    this.#welcome = false;
    this.#pickToken += 1;
    this.#leaveOpen();
    this.openBusy = false;
  }

  close() {
    this.#pickToken += 1;
    this.open = false;
  }

  // ---- Step navigation ----
  goToStep(id: WizardStepId) {
    const index = indexOfStep(this.steps, id);
    // Breadcrumb navigation is backward-only: a completed step navigates back,
    // but a future step is unreachable by click (the consistency gate owns
    // forward motion through Next).
    if (index >= 0 && index < this.currentIndex) {
      this.#stepIndex = index;
      if (id === "start") this.#leaveOpen();
    }
  }

  back() {
    if (this.#stepIndex > 0) this.#stepIndex -= 1;
    if (this.currentStep.id === "start") this.#leaveOpen();
  }

  // ---- First-run Welcome step (#2467) ----
  chooseCreate() {
    if (this.currentStep.id !== "start") return;
    this.#pickToken += 1;
    this.openError = "";
    if (this.needsRootFolder) {
      this.#stepIndex = indexOfStep(this.steps, "root");
      return;
    }
    // The root is already saved (a failed open got that far): skip the root step
    // and land on Location, exactly where a successful root save would.
    this.#welcome = false;
    this.#stepIndex = 0;
    this.#seedLocationFromDefault();
  }

  chooseOpen() {
    if (this.currentStep.id !== "start") return;
    this.#pickToken += 1;
    this.openError = "";
    this.pickerMode = "open";
    this.pickerOpen = true;
  }

  // The picked folder must itself be a project; the suggested projects folder is
  // the parent of the topmost ancestor project (see openExistingProject.ts).
  async #pickExisting(path: string) {
    const token = ++this.#pickToken;
    // Superseded (Create chosen, closed, reset, newer pick) or no longer on Welcome.
    const stale = () => token !== this.#pickToken || !this.open || this.currentStep.id !== "start";
    this.openError = "";
    try {
      const listing = await api.listDirectories(path);
      if (stale()) return;
      if (!listing.is_project) {
        this.openError = "That folder isn't a project — pick the folder that holds project.yaml.";
        return;
      }
      if (!listing.parent_path) {
        // Nothing above it to be the projects folder, so containment can never hold.
        this.openError =
          "A project at the top of a drive can't be opened — move it into a folder first.";
        return;
      }
      const suggestion = await suggestProjectsFolder(listing, (next) => api.listDirectories(next));
      if (stale()) return;
      this.rootFolderDraft = suggestion;
      this.openProjectPath = listing.path;
      this.#opening = true;
      this.#stepIndex = indexOfStep(this.steps, "open_root");
    } catch (error) {
      if (stale()) return;
      this.openError = error instanceof Error ? error.message : "Could not read that folder.";
    }
  }

  #leaveOpen() {
    if (!this.#opening) return;
    this.#opening = false;
    this.openProjectPath = "";
    this.rootFolderDraft = "";
    this.openError = "";
    this.aiPolicy = "inherit";
    this.#stepIndex = 0;
  }

  // Save the chosen projects folder, persist the first-run app-wide AI policy
  // (#746 - the same write submit() does), then open the project under it. Any of
  // them failing keeps the wizard open on this step with the reason shown inline.
  async confirmOpen() {
    if (this.currentStep.id !== "open_root" || !this.canAdvance || this.openBusy) return;
    this.openBusy = true;
    this.openError = "";
    try {
      await this.onSaveRootFolder(this.rootFolderDraft.trim());
      if (this.needsRootFolder) {
        this.openError = "Couldn't use that folder — check that the path exists.";
        return;
      }
      if (this.#aiPolicyToPersist && !(await this.#saveAppPolicy(this.#aiPolicyToPersist))) {
        this.openError = "Couldn't save the AI policy.";
        return;
      }
      if (!(await this.onOpenProject(this.openProjectPath))) {
        this.openError = "Couldn't open that project.";
        return;
      }
      this.close();
    } finally {
      this.openBusy = false;
    }
  }

  async #saveAppPolicy(policy: AIPolicy): Promise<boolean> {
    try {
      return (await this.onSaveAppPolicy(policy)) !== false;
    } catch {
      return false;
    }
  }

  async next() {
    // The view gates Next on canAdvance; guard anyway so a stray call is inert.
    if (!this.canAdvance) return;
    if (this.currentStep.id === "root") {
      this.rootError = "";
      await this.onSaveRootFolder(this.rootFolderDraft.trim());
      // On FAILURE (e.g. the folder does not exist) the host swallows the error
      // into App's toast — which sits behind this modal — and needsRootFolder
      // stays true. Advancing anyway would build a project with no machine root
      // (a chain-of-one). So stay on the step and surface the failure here.
      if (this.needsRootFolder) {
        this.rootError = "Couldn't use that folder — check that the path exists.";
        return;
      }
      // On SUCCESS the save flips needsRootFolder ⇒ the step list drops "start"
      // and "root", shifting "location" into #stepIndex 0. Land there explicitly
      // (the collapse is the advance; the old index, past "start", would now
      // point at "ai").
      // Falling through to the increment below skipped straight past "location"
      // to "ai", leaving the title uncollected → an empty-title 422 (#1404). This
      // used to be safe only because "location" was once the final step.
      //
      // First run only reaches a machine root now, so seed the Location with it
      // here (start() handled the returning-user case) — #1410.
      this.#welcome = false;
      this.#stepIndex = 0;
      this.#seedLocationFromDefault();
      return;
    }
    if (!this.isFinalStep) {
      this.#stepIndex += 1;
      // The AI step's "inherit" note names the resolved policy + its source;
      // resolve it on entry, now the location step has settled the ancestry
      // (#1672). Same forward-fetch shape as the review step below.
      if (this.currentStep.id === "ai") void this.#loadInheritedPolicy();
      // The review step resolves the project node against the chain declared at
      // the location step; fetch it on entry (the AI step between them cannot
      // change the ancestry). Re-entering after a Back re-fetches — cheap, and
      // it keeps the inherited picture honest if the declaration changed.
      if (this.currentStep.id === "review") void this.#loadReview();
    }
  }

  async #loadInheritedPolicy() {
    // Nothing ticked ⇒ no inherit state on the slider, so nothing to resolve.
    if (this.inherits.length === 0) {
      this.inheritedPolicy = null;
      return;
    }
    try {
      this.inheritedPolicy = await api.prospectiveAiPolicy(this.resolvedRoot, this.inherits);
    } catch {
      // Degrade silently — the inherit note falls back to its generic copy.
      this.inheritedPolicy = null;
    }
  }

  async #loadReview() {
    this.reviewLoading = true;
    try {
      const node = await api.prospectiveProjectNode(this.resolvedRoot, this.inherits);
      this.reviewSchema = node.metadata_schema;
      this.reviewInherited = node.metadata;
      this.reviewSources = node.field_sources;
      this.#seedLocaleDefaults();
    } catch (error) {
      this.reviewSchema = null;
      this.onError(
        error instanceof Error ? error.message : "Could not resolve the project's settings.",
      );
    } finally {
      this.reviewLoading = false;
    }
  }

  // Seed the review overrides from the browser locale (#1415) — once per
  // location, only for world-canon fields the resolved chain doesn't already
  // state, so inheritance and author edits are never clobbered. Each seeded key
  // renders as a shown, overridable value (a "Reset to default" affordance).
  #seedLocaleDefaults() {
    if (this.#localeSeeded) return;
    this.#localeSeeded = true;
    const locale = typeof navigator !== "undefined" ? navigator.language : "";
    const seed: Record<string, MetadataValue> = {};
    for (const [fieldId, value] of Object.entries(localeProjectDefaults(locale))) {
      if (value != null && !(fieldId in this.reviewInherited)) {
        seed[fieldId] = value;
      }
    }
    if (Object.keys(seed).length > 0) {
      this.nodeOverrides = { ...this.nodeOverrides, ...seed };
    }
  }

  // ---- Directory picker ----
  openPicker() {
    this.pickerOpen = true;
  }

  closePicker() {
    this.pickerOpen = false;
    this.pickerMode = "location";
  }

  onPickFolder(path: string) {
    const mode = this.pickerMode;
    this.closePicker();
    if (mode === "open") {
      void this.#pickExisting(path);
      return;
    }
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
    // The new chain resolves fresh, so re-seed locale defaults for it (#1415).
    this.#localeSeeded = false;
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
    this.hireModelLabel = "";
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

  setHireProvider(
    provider: string,
    tier: AICapabilityTier | "",
    model: string,
    modelLabel = "",
  ) {
    this.hireProvider = provider;
    this.hireTier = tier;
    this.hireModel = model;
    this.hireModelLabel = modelLabel;
  }

  async submitHire() {
    await this.#withBusy(async () => {
      await this.onHireAssistant(
        // Author's name wins; else the model's display name; else a last-resort
        // generic, so hires read as the models chosen, not identical rows (#1412).
        this.hireTitle.trim() || this.hireModelLabel.trim() || "New assistant",
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
    // canComplete, not canAdvance: the last step's advance gate is always true,
    // so completion re-checks the actual required fields (#1404).
    if (!this.isFinalStep || !this.canComplete) return;
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
