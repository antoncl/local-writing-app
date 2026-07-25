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

export type PlotTemplatePoint = {
  id: string;
  title: string;
  function_claim: string;
  description: string;
  guidance: string;
  required: boolean;
  sort_order: number;
  metadata: Record<string, unknown>;
};

export type PlotTemplateSpec = {
  version: number;
  plot_points: PlotTemplatePoint[];
  metadata: Record<string, unknown>;
};

export type PlotTemplateInstancePoint = {
  plot_point_id: string;
  title: string;
  function_claim: string;
  notes: string;
  metadata: Record<string, unknown>;
};

export type PlotTemplateInstanceSpec = {
  template_id: string;
  plot_points: PlotTemplateInstancePoint[];
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
  function_claim: string;
  description: string;
  guidance: string;
  notes: string;
};

export type PlotContextTemplateInstance = {
  id: string;
  title: string;
  template_id: string;
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

