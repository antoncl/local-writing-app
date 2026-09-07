// Project / project-chain wire types. Extracted from types.ts to keep that
// barrel under the file-size cap; re-exported from `@/lib/types` so it stays
// the single import surface.

import type { AIPolicy } from "./aiTypes";
import type { MetadataSchema } from "./schemaTypes";
import type { MetadataValue } from "./metadataTypes";
import type { CodeFencedBody } from "./manuscriptTypes";

// The wizard review pane's inputs for a *not-yet-created* project (#318 slice
// 4). The prospective twin of `ProjectInfo.metadata` (#317) plus the provenance
// that field omits: the merged schema over the ticked chain (so a select shows
// an ancestor's added vocabulary), the inherited values (nearest-explicit-wins;
// a key no ancestor states is absent and the pane falls to the schema default),
// and the ancestor layer that supplied each resolved key — the "Reset to
// <source>" label (§8).
export type ProspectiveProjectNode = {
  metadata_schema: MetadataSchema;
  metadata: Record<string, MetadataValue>;
  field_sources: Record<string, string>;
};

// The wizard AI step's inherited-policy preview (#1672): the resolved policy over
// the ticked chain, and the ancestor that stated it (null = the app default).
export type ProspectiveAiPolicy = {
  policy: AIPolicy;
  source: string | null;
};

export type ProjectValidation = {
  valid: boolean;
  warnings: string[];
  errors: string[];
  migrations_applied: string[];
  code_fenced_bodies: CodeFencedBody[];
};

/**
 * One folder between the configured base and the open project (#309).
 *
 * Every ancestor is reported, not only the inheritable ones: `is_project`
 * false means an organisational folder, which the wizard shows marked rather
 * than omits — a gap in the list reads as a bug, and the marking doubles as a
 * quiet warning that a folder up there was never made into a project.
 */
export type AncestorCandidate = {
  path: string;
  name: string;
  is_project: boolean;
  inherited: boolean;
  /** What the project calls itself; null when the folder is not a project. */
  title?: string | null;
};

/** A project folder directly inside this one — the roster #310 renders. */
export type ProjectChild = {
  path: string;
  name: string;
  title: string;
};

/**
 * One layer of the breadcrumb chain, outermost first, the open project last
 * (#432; state added for #417 slice 4).
 *
 * Still named by the backend walker, never re-derived client-side — that
 * duplication, and its disagreement over labels, is what #432 removed. Since
 * slice 4 the chain also carries every ancestor project + stale declaration
 * with its `is_project`/`inherited` state, so the bar can render a skipped
 * layer dimmed and a stale one flagged rather than hide a legal gap (the
 * reversal of #431). `is_project` × `inherited` gives declared / available /
 * stale; a pure organisational folder is omitted from the chain entirely.
 */
export type ProjectChainLayer = {
  id: string;
  label: string;
  path: string;
  /** The open project itself, always last. */
  is_root: boolean;
  is_project: boolean;
  inherited: boolean;
};

export type ProjectInfo = {
  title: string;
  root_path: string;
  projects_base_folder?: string | null;
  ai_policy: AIPolicy;
  /**
   * Whether `ai_policy` is inherited from an ancestor (this project states
   * none of its own) rather than set here (#471). Lets the Project pane show
   * the "Inherit" option as selected; *which* ancestor supplied the value is
   * provenance (#313), not carried here.
   */
  ai_policy_inherited: boolean;
  /** The whole enumeration, outermost first, matching layer rank. */
  ancestors?: AncestorCandidate[];
  /** The declared subset of the same walk, resolved and labelled server-side. */
  chain?: ProjectChainLayer[];
  children?: ProjectChild[];
  /**
   * The project node's authored fields (project.md), resolved nearest-explicit-
   * wins over the inheritance chain (#317) — the same fold as `ai_policy`. This
   * is the value the AI templates read as `project.metadata.*`; a field no layer
   * sets is simply absent.
   */
  metadata?: Record<string, unknown>;
};

export type ProjectNode = {
  id: string;
  title: string;
  body: string;
  revision: string;
  entry_type: string;
  metadata: Record<string, unknown>;
  computed_metadata: Record<string, unknown>;
};

export type SaveProjectNodeRequest = {
  title: string;
  body: string;
  base_revision?: string | null;
  entry_type?: string;
  metadata?: Record<string, unknown>;
};

// The running application version (ADR-0072 S2), from `GET /api/version`.
export type AppVersion = {
  version: string;
  // The commit this binary was frozen at (ADR-0072 S6); null in a source run
  // or a frozen build with no baked stamp. The nightly update check compares it.
  build: string | null;
};
