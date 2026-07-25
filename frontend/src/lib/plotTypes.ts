import type { EntryMetadata, Scene, StructureDocument } from "./types";

export type PlotClaimType =
  | "satisfies"
  | "partially_satisfies"
  | "subverts"
  | "foreshadows"
  | "pays_off"
  | "raises_question"
  | "rejects"
  | "custom";

export type PlotTemplateFamily =
  | "act"
  | "journey"
  | "cycle"
  | "genre"
  | "puzzle"
  | "relationship"
  | "character_arc"
  | "custom";

export type PlotTemplatePrescriptiveness = "descriptive" | "diagnostic" | "prescriptive";
export type PlotTemplateIPRisk = "low" | "medium" | "high" | "unknown";
export type PlotTemplateBuiltinPolicy = "seed" | "seed_generic" | "reference_only" | "user_authored";
export type PlotPointNoteStatus =
  | "unplanned"
  | "planned"
  | "drafted"
  | "satisfied"
  | "intentionally_omitted";

export type SourceRef = {
  id: string;
  title?: string;
  url?: string | null;
  citation?: string;
  note?: string;
  metadata?: Record<string, unknown>;
};

export type PlotPointFunction = {
  claim?: string;
  description?: string;
  metadata?: Record<string, unknown>;
};

export type PlotPointPlacement = {
  phase_label?: string;
  target_position?: number | null;
  min_position?: number | null;
  max_position?: number | null;
  structure_hint?: string;
  metadata?: Record<string, unknown>;
};

export type PlotPointCompression = {
  can_compress?: boolean | null;
  can_expand?: boolean | null;
  merge_with_point_ids?: string[];
  guidance?: string;
  metadata?: Record<string, unknown>;
};

export type PlotPointAIRubric = {
  criteria?: string[];
  evidence_prompts?: string[];
  failure_signals?: string[];
  guidance?: string;
  metadata?: Record<string, unknown>;
};

export type PlotTemplatePoint = {
  id: string;
  key?: string;
  title: string;
  label?: string;
  label_variants?: string[];
  short_label?: string;
  phase_label?: string;
  parent_point_id?: string | null;
  order_index?: number;
  function_claim: string;
  function?: PlotPointFunction;
  description: string;
  guidance: string;
  required: boolean;
  sort_order: number;
  placement?: PlotPointPlacement | null;
  diagnostic_questions?: string[];
  failure_modes?: string[];
  compression?: PlotPointCompression | null;
  claim_evidence_prompts?: string[];
  ai_rubric?: PlotPointAIRubric | null;
  source_ref_ids?: string[];
  metadata: Record<string, unknown>;
};

export type PlotTemplateSpec = {
  version: number;
  slug?: string;
  display_name?: string;
  aliases?: string[];
  family?: PlotTemplateFamily;
  description?: string;
  cultural_context?: string;
  prescriptiveness?: PlotTemplatePrescriptiveness;
  ai_use_guidance?: string;
  global_diagnostic_questions?: string[];
  supports_compression?: boolean;
  supports_expansion?: boolean;
  source_refs?: SourceRef[];
  ip_risk?: PlotTemplateIPRisk;
  builtin_policy?: PlotTemplateBuiltinPolicy;
  template_version?: string;
  locale?: string;
  /** Legacy/current emitted name. Backend also accepts design-doc `points`. */
  plot_points?: PlotTemplatePoint[];
  /** Design-doc input alias accepted by the backend. Responses use `plot_points`. */
  points?: PlotTemplatePoint[];
  metadata: Record<string, unknown>;
};

export type PlotTemplateInstancePoint = {
  plot_point_id: string;
  title: string;
  local_label?: string;
  function_claim: string;
  notes: string;
  author_intent?: string;
  expected_role?: string;
  open_questions?: string[];
  status?: PlotPointNoteStatus;
  metadata: Record<string, unknown>;
};

export type PlotPointInstanceNote = {
  local_label?: string;
  author_intent?: string;
  expected_role?: string;
  open_questions?: string[];
  status?: PlotPointNoteStatus;
  notes?: string;
  metadata?: Record<string, unknown>;
};

export type PlotTemplateInstanceSpec = {
  /** Legacy/current emitted name. Backend also accepts design-doc `template_ref`. */
  template_id: string;
  /** Design-doc input alias accepted by the backend. Responses use `template_id`. */
  template_ref?: string;
  title?: string;
  enabled_point_ids?: string[];
  plot_points?: PlotTemplateInstancePoint[];
  point_notes?: Record<string, PlotPointInstanceNote>;
  source_layer_id?: string;
  source_layer_label?: string;
  metadata: Record<string, unknown>;
};

export type PlotLine = {
  id: string;
  title: string;
  template_instance_id?: string | null;
  color?: string | null;
  metadata: Record<string, unknown>;
};

export type PlotBoardCard = {
  id: string;
  title: string;
  synopsis: string;
  node_ref?: string | null;
  structure_column_id?: string | null;
  primary_plotline_id?: string | null;
  metadata: Record<string, unknown>;
};

export type PlotPointClaim = {
  id: string;
  card_id: string;
  template_instance_id: string;
  plot_point_id: string;
  plotline_id?: string | null;
  claim_type: PlotClaimType;
  claim_label?: string | null;
  strength?: "weak" | "medium" | "strong" | null;
  confidence?: number | null;
  evidence?: string | null;
  rationale?: string | null;
  ai_notes?: string | null;
  metadata: Record<string, unknown>;
};

export type PlotRelationship = {
  id: string;
  from_card_id: string;
  to_card_id: string;
  kind: "causes" | "blocks" | "reveals" | "setup_payoff" | "echoes" | "contrasts" | "custom";
  label?: string | null;
  metadata: Record<string, unknown>;
};

export type PlotBoardSpec = {
  version: number;
  template_instance_ids: string[];
  plotlines: PlotLine[];
  cards: PlotBoardCard[];
  claims: PlotPointClaim[];
  relationships: PlotRelationship[];
  metadata: Record<string, unknown>;
};

export type PlotContextCard = {
  id: string;
  title: string;
  synopsis: string;
  scene_id?: string | null;
  structure_node_id?: string | null;
  structure_title?: string | null;
  manuscript_index?: number | null;
  primary_plotline_id?: string | null;
};

export type PlotContextClaim = {
  id: string;
  card_id: string;
  template_instance_id: string;
  plot_point_id: string;
  plotline_id?: string | null;
  claim_type: PlotClaimType;
  claim_label?: string | null;
  strength?: "weak" | "medium" | "strong" | null;
  evidence?: string | null;
  rationale?: string | null;
  ai_notes?: string | null;
};

export type PlotContextPoint = {
  plot_point_id: string;
  title: string;
  local_label?: string;
  function_claim: string;
  description: string;
  guidance: string;
  notes: string;
  author_intent?: string;
  expected_role?: string;
  open_questions?: string[];
  status?: PlotPointNoteStatus;
  placement?: PlotPointPlacement | null;
  diagnostic_questions: string[];
  failure_modes: string[];
  compression?: PlotPointCompression | null;
  claim_evidence_prompts: string[];
  ai_rubric?: PlotPointAIRubric | null;
};

export type PlotContextTemplateInstance = {
  id: string;
  title: string;
  template_id: string;
  template_slug?: string;
  template_family?: PlotTemplateFamily;
  template_description?: string;
  ai_use_guidance?: string;
  global_diagnostic_questions?: string[];
  plot_points: PlotContextPoint[];
};

export type PlotContextRelationship = {
  id: string;
  from_card_id: string;
  to_card_id: string;
  kind: PlotRelationship["kind"];
  label?: string | null;
};

export type PlotContextPacket = {
  board_id: string;
  board_title: string;
  scope_scene_id?: string | null;
  include_future: boolean;
  cards: PlotContextCard[];
  claims: PlotContextClaim[];
  template_instances: PlotContextTemplateInstance[];
  plotlines: PlotLine[];
  relationships: PlotContextRelationship[];
  omitted_counts: Record<string, number>;
};

export type PlotLayoutNode = {
  id: string;
  kind: string;
  position: Record<string, number>;
  cfg: Record<string, unknown>;
};

export type PlotLayoutEdge = {
  id: string;
  source: string;
  target: string;
  source_handle?: string | null;
  target_handle?: string | null;
};

export type PlotViewport = { x: number; y: number; zoom: number };

export type PlotBoardLayout = {
  nodes: PlotLayoutNode[];
  edges: PlotLayoutEdge[];
  viewport?: PlotViewport | null;
};

export type PlotNodeSummary = {
  id: string;
  title: string;
  entry_type: string;
  system: boolean;
  source_layer_id?: string;
  source_layer_label?: string;
};

export type PlotNode = {
  id: string;
  title: string;
  revision: string;
  entry_type: string;
  body: string;
  template?: PlotTemplateSpec | null;
  template_instance?: PlotTemplateInstanceSpec | null;
  board?: PlotBoardSpec | null;
  layout?: PlotBoardLayout | null;
  system: boolean;
  source_layer_id?: string;
  source_layer_label?: string;
  metadata: EntryMetadata;
  computed_metadata: EntryMetadata;
};

export type PlotNodeList = { entries: PlotNodeSummary[] };

export type CreatePlotNodeRequest = {
  title: string;
  entry_type?: string;
  body?: string;
  metadata?: EntryMetadata;
  template?: PlotTemplateSpec | null;
  template_instance?: PlotTemplateInstanceSpec | null;
  board?: PlotBoardSpec | null;
  layout?: PlotBoardLayout | null;
};

export type SavePlotNodeRequest = CreatePlotNodeRequest & {
  base_revision?: string | null;
};

export type PromotePlotCardRequest = {
  card_id: string;
  title?: string | null;
  parent_id?: string | null;
  base_revision?: string | null;
};

export type PromotePlotCardResponse = {
  plot: PlotNode;
  scene: Scene;
  structure: StructureDocument;
};
