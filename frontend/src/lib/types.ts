// The barrel of the frontend's wire/domain types. Each domain lives in a
// sibling `<domain>Types.ts` module (workspaceTypes, manuscriptTypes,
// loreTypes, …); `@/lib/types` stays the one import surface across the app.
// Nothing is defined here — only re-exported.

// Snapshot / diff wire types live in ./snapshotTypes (extracted to keep this
// module under the file-size cap). Re-exported so `@/lib/types` stays the one
// import surface.
export type {
  Snapshot,
  SnapshotList,
  SnapshotDetail,
  DiffView,
  DiffRun,
  FieldDiff,
  WitnessFieldDrift,
  FieldReinterpretation,
  EntityDrift,
  SnapshotDrift,
} from "./snapshotTypes";

// Plot types (ADR-0048) live in sibling files — templates (S4b/S4c), the board
// projection (S7a/S7b), and cards + plotlines (S5a/S5b) — to keep this file under
// the size cap; re-exported so `@/lib/types` stays the single import barrel.
export type {
  PlotTemplate,
  PlotTemplateSummary,
  PlotTemplateList,
  PlotTemplateSpec,
  PlotTemplateSourceRef,
} from "./plotTemplateTypes";
export type {
  PlotBoardProjection,
  PlotBoardCard,
  PlotBoardBeat,
  PlotCardBeat,
  PlotBoardContainer,
  PlotBoardPlotline,
  PlotBoardPlotlineBeat,
  PlotBoardCharacterArc,
  PlotBoardLayout,
  PlotBoard,
  PlotDiagnostic,
  PlotDiagnosticCard,
  PlotDiagnosticEdge,
  BoardXY,
  BoardSize,
} from "./plotBoardTypes";
export type {
  CardEntry,
  CardSummary,
  CardList,
  PlotlineEntry,
  PlotlineSummary,
  PlotlineList,
  CharacterArcEntry,
  CharacterArcSummary,
  CharacterArcList,
} from "./plotCardTypes";

// Machine-settings wire types live in ./machineTypes (#763.5) — extracted to
// keep this barrel under the file-size cap; re-exported so `@/lib/types` stays
// the one import surface.
export type {
  ProviderCredentialsView,
  RecentProject,
  Swatch,
  DisplaySettings,
  MachineSettingsView,
  MachineSettingsUpdate,
  MachineSettingsDraft,
  UpdateChannel,
  UpdateCheck,
} from "./machineTypes";

// AI wire types live in ./aiTypes (#763.5) — extracted to keep this barrel
// under the file-size cap; re-exported so `@/lib/types` stays the one import
// surface. (`projectTypes` imports `AIPolicy` from ./aiTypes directly.)
export type {
  AIPolicy,
  AIHealthResponse,
  OllamaHostHealth,
  AIProviderInfo,
  AIProviderList,
  AICapabilityTier,
  AIModelInfo,
  AIProviderModelList,
  AITierResolution,
  AIPreviewRequest,
  PreviewContentBlock,
  PreviewMessage,
  PreviewCacheBlock,
  PreviewErrorInfo,
  AIPreviewResponse,
  PromptInputConflict,
  ChatEstimate,
  ChatMessage,
  AIChatRequest,
  ChatUsage,
  LoreFit,
  LoreFitEntry,
  LoreSource,
  AIChatResponse,
  AIGenerateRequest,
  AIContextPresetResponse,
  AIGenerateResponse,
  AIInvocation,
  AIInvocationList,
  CreateAIInvocationRequest,
  AICostBucket,
  AICostSummary,
  ChatSessionMessage,
  ChatSessionContextItem,
  ChatSessionJournalEntry,
  ChangedPick,
  ChatSession,
  ChatSessionSummary,
  ChatSessionList,
  CreateChatSessionRequest,
  SaveChatSessionRequest,
} from "./aiTypes";

export * from "./workspaceTypes";
export * from "./manuscriptTypes";
export * from "./loreTypes";
export * from "./documentTypes";
export * from "./promotionTypes";
export * from "./promptTypes";
export * from "./assistantTypes";
export * from "./tagTypes";
export * from "./metadataTypes";
export * from "./entryPatchTypes";
export * from "./schemaTypes";
export * from "./viewTypes";
export * from "./pickerTypes";
export * from "./projectTypes";
export * from "./todoTypes";
export * from "./mutationTypes";
export * from "./filesystemTypes";
export * from "./searchTypes";
export * from "./referenceTypes";
